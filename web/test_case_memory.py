"""Synthetic case data only. No external API calls or real medical records."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from web import case_memory as store
from web.case_context import prepare_context, retrieve, synchronize_index
from web.app import app


def fact(value="13.91", date="2026-10-01"):
    return dict(name="葡萄糖",value=value,unit="mmol/L",reference="3.9-6.1",method="己糖激酶法",date=date,conditions="空腹",certainty="clear")


def operation(action="add", value="13.91", target=None, **changes):
    data=fact(value)
    data.update(changes)
    return dict(action=action,source="user",quote=value,target_id=target["id"] if target else "",
                expected_revision=target["revision"] if target else None,fact=data)


class FakeVector(list):
    def tolist(self):return list(self)


class FakeMilvus:
    def __init__(self):self.rows={};self.created=False;self.failed=False
    def has_collection(self,*_):return self.created
    def create_collection(self,**_):self.created=True
    def load_collection(self,*_):pass
    def get(self,_,ids,**kwargs):return [self.rows[key] for key in ids if key in self.rows]
    def upsert(self,collection_name,data):
        if self.failed:raise RuntimeError("Synthetic index failure")
        self.rows.update({row["id"]:row for row in data})
    def search(self,**kwargs):
        # Deliberately ignore the filter: the caller must enforce ownership too.
        return [[{"id":key,"entity":row} for key,row in self.rows.items()]]


class CaseMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.dbpatch=patch.object(store,"DB_PATH",Path(self.temp.name)/"cases.sqlite3");self.dbpatch.start()
        self.counter=0
        self.kb=SimpleNamespace(embedding_dim=2,milvus_client=FakeMilvus(),embedding_model=SimpleNamespace(encode=lambda values:[FakeVector([1.,0.]) for _ in values]))

    def tearDown(self):self.dbpatch.stop();self.temp.cleanup()

    def apply(self,ops,owner="a",chat="chat",case="",message=None,request=None,**proposal):
        self.counter+=1
        return store.apply_changes(owner,chat,case,request or str(self.counter),dict(operations=ops,questions=[],**proposal),message or " ".join(op["quote"]+" "+json.dumps(op["fact"],ensure_ascii=False) for op in ops),"")

    def first(self):
        result=self.apply([operation()]);return result,store.current_facts("a",result["case_id"])[0]

    def test_correction_replaces_current_value_and_keeps_audit(self):
        result,old=self.first()
        changed=self.apply([operation("correct","6.9",old)],case=result["case_id"])
        latest=store.current_facts("a",result["case_id"])
        self.assertEqual(len(latest),1);self.assertEqual(latest[0]["data"]["value"],"6.9");self.assertEqual(latest[0]["revision"],2)
        with store.database() as db:self.assertEqual(db.execute("SELECT count(*) FROM versions").fetchone()[0],2)
        self.assertEqual(changed["changes"][0]["action"],"correct")

    def test_new_measurement_does_not_overwrite_previous(self):
        result,old=self.first();self.apply([operation(value="6.9",date="2026-10-29")],case=result["case_id"])
        rows=store.current_facts("a",result["case_id"])
        self.assertEqual(len(rows),2)
        trend=store.trends(rows)[0];self.assertTrue(trend["comparable"]);self.assertEqual(trend["delta"],"-7.01")

    def test_supplement_preserves_value_and_unmentioned_fields(self):
        result,old=self.first();op=operation("supplement","餐后",old);op["fact"]={"conditions":"餐后"}
        self.apply([op],case=result["case_id"])
        updated=store.current_facts("a",result["case_id"])[0]
        self.assertEqual(updated["data"]["value"],"13.91");self.assertEqual(updated["data"]["conditions"],"餐后")

    def test_retries_are_idempotent(self):
        one=self.apply([operation()],request="same");two=self.apply([operation()],request="same")
        self.assertEqual(one,two);self.assertEqual(len(store.current_facts("a",one["case_id"])),1)

    def test_unknown_or_stale_target_becomes_question(self):
        result,old=self.first();self.apply([operation("correct","6.9",old)],case=result["case_id"])
        stale=self.apply([operation("correct","7.0",old)],case=result["case_id"])
        self.assertFalse(stale["changes"]);self.assertTrue(stale["questions"])

    def test_no_unanchored_values_or_inferred_disease_are_saved(self):
        op=operation();op["fact"]["value"]="999"
        result=self.apply([op],message="13.91")
        self.assertFalse(result["changes"]);self.assertFalse(store.list_cases("a"))

    def test_cross_case_or_owner_edits_cannot_change_facts(self):
        result,old=self.first()
        other=self.apply([operation(value="4.0")],owner="b")
        denied=self.apply([operation("correct","6.9",old)],owner="b",case=other["case_id"])
        self.assertFalse(denied["changes"])
        with self.assertRaises(LookupError):store.current_facts("b",result["case_id"])

    def test_patient_switch_never_modifies_prior_patient(self):
        result,old=self.first()
        newer=self.apply([operation(value="4.0")],case=result["case_id"],new_patient=True)
        self.assertNotEqual(newer["case_id"],result["case_id"])
        self.assertEqual(store.current_facts("a",result["case_id"])[0]["data"]["value"],"13.91")
        empty=self.apply([],case=newer["case_id"],new_patient=True)
        self.assertEqual(store.bound_case("a","chat"),empty["case_id"])

    def test_trends_require_all_comparability_conditions(self):
        result,old=self.first();self.apply([operation(value="6.9",date="2026-10-29",method="")],case=result["case_id"])
        trend=store.trends(store.current_facts("a",result["case_id"]))[0]
        self.assertFalse(trend["comparable"]);self.assertIsNone(trend["delta"])

    def test_previous_analysis_is_stale_after_revision(self):
        result,old=self.first();store.save_analysis("a",result["case_id"],"synthetic",[old])
        with store.database() as db:analysis=db.execute("SELECT id FROM analyses").fetchone()[0]
        self.assertFalse(store.analysis_is_stale("a",analysis))
        self.apply([operation("correct","6.9",old)],case=result["case_id"])
        self.assertTrue(store.analysis_is_stale("a",analysis))

    def test_upsert_replaces_old_vector_content_and_owner_filter_is_rechecked(self):
        result,old=self.first();synchronize_index(self.kb,[old])
        self.apply([operation("correct","6.9",old)],case=result["case_id"])
        rows=store.current_facts("a",result["case_id"])
        other=self.apply([operation(value="4.0")],owner="b")
        synchronize_index(self.kb,store.current_facts("b",other["case_id"]))
        found=retrieve(self.kb,"a",result["case_id"],"血糖",rows)
        self.assertEqual([row["data"]["value"] for row in found],["6.9"])
        self.assertNotIn('13.91',self.kb.milvus_client.rows[old["id"]]["content"])

    def test_sqlite_persists_across_connections_and_other_browser_sees_no_cases(self):
        result,_=self.first();self.assertEqual(store.list_cases("a")[0]["id"],result["case_id"])
        other=TestClient(app);other.cookies.set("medix_browser","b"*32)
        self.assertEqual(other.get("/api/cases").json()["cases"],[])

    def test_failed_index_update_uses_latest_sqlite_and_not_old_value(self):
        result,old=self.first();synchronize_index(self.kb,[old]);self.kb.milvus_client.failed=True
        proposal=dict(operations=[operation("correct","6.9",old)],questions=[])
        import asyncio
        with patch("web.case_context.propose_changes",AsyncMock(return_value=proposal)):
            prepared=asyncio.run(prepare_context("a","chat",result["case_id"],"new-turn","6.9","",self.kb))
        self.assertFalse(prepared["index_ready"])
        self.assertEqual(prepared["facts"][0]["data"]["value"],"6.9")
        self.assertNotIn('13.91',prepared["context"])

    def test_uncertain_and_non_numeric_results_are_not_range_classified(self):
        _,row=self.first();row["data"]["certainty"]="uncertain"
        self.assertIn("不自动判定",store.range_check(row))

    def test_inferred_metadata_and_upload_date_are_not_saved(self):
        result=self.apply([operation()],message="葡萄糖13.91")
        saved=store.current_facts("a",result["case_id"])[0]["data"]
        for key in ("unit","reference","method","date","conditions"):
            self.assertEqual(saved[key],"")

    def test_image_markdown_does_not_block_source_anchor(self):
        image="**检验时间**：2018-05-22\n* **5 TBIL 总胆红素**：26.3 ↑ umol/L（参考范围：0.0~21.0）\n* **GLU 空腹血糖**：5.00 mmol/L（参考范围：3.89~6.11）"
        op=dict(action="add",source="image",quote="总胆红素 26.3 umol/L",fact=dict(name="总胆红素（TBIL）",value="26.3",unit="umol/L",reference="0.0-21.0",method="",date="2018-05-22",conditions="",certainty="clear"))
        result=store.apply_changes("a","chat","","image-request",dict(operations=[op],questions=[]),"帮我看看",image)
        saved=store.current_facts("a",result["case_id"])[0]["data"]
        self.assertEqual(saved["value"],"26.3");self.assertEqual(saved["date"],"2018-05-22");self.assertEqual(saved["reference"],"0.0-21.0")
        self.assertEqual(store.range_check({"data":saved}),"高于单据范围")

    def test_image_range_from_another_row_is_not_attached(self):
        image="TBIL 总胆红素：26.3 umol/L（参考范围0.0~21.0）\nGLU 空腹血糖：5.00 mmol/L（参考范围3.89~6.11）"
        op=dict(action="add",source="image",quote="总胆红素26.3",fact=dict(name="总胆红素",value="26.3",unit="umol/L",reference="3.89-6.11"))
        result=store.apply_changes("a","chat","","image-request",dict(operations=[op],questions=[]),"帮我看看",image)
        self.assertEqual(store.current_facts("a",result["case_id"])[0]["data"]["reference"],"")


if __name__=="__main__":unittest.main()
