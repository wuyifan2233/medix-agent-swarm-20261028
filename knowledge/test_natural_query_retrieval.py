"""Natural-language recall and post-retrieval relevance, without services."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
from knowledge.evidence import EvidenceKnowledgeBase
from knowledge.query_policy import contextualize_query, directly_relevant


class NaturalQueryRetrievalTests(unittest.TestCase):
    def retrieve(self, query, title, content, score=.8):
        row={'id':'one','content':content,'metadata':{'doc_id':'neck','title':title,
             'topics':[],'audiences':['general'],'type':'health'}}
        kb=SimpleNamespace(documents=[],version='test',reranker=None,_lock=threading.Lock(),
            embedding_model=SimpleNamespace(encode_query=Mock(return_value=np.array([1.,0.]))),
            milvus_client=SimpleNamespace(search=Mock(return_value=[[{'id':'one','distance':score}]])),
            collection_name='test',lexical=SimpleNamespace(get_scores=lambda _:np.array([1.])),
            rows=[row],by_id={'one':row},document_vectors={})
        with patch('knowledge.evidence.similarity_threshold',return_value=.4):
            result=EvidenceKnowledgeBase.retrieve(kb,query)
        return result,kb

    def test_colloquial_neck_question_reaches_search_without_registered_topic(self):
        result,kb=self.retrieve('久坐后肩颈不舒服，日常可以怎样调整习惯？',
                               '颈椎病日常注意事项','颈部活动与坐姿调整，避免长时间低头。')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['hits']),1)
        kb.embedding_model.encode_query.assert_called_once()
        kb.milvus_client.search.assert_called_once()

    def test_below_threshold_still_returns_zero(self):
        result,_=self.retrieve('脖子酸怎么调整坐姿','颈部护理','颈部活动和坐姿调整',.39)
        self.assertEqual(result['hits'],[])
        self.assertEqual(result['status'],'no_results')

    def test_unrelated_high_score_does_not_fill_slots(self):
        for title,content in [('细菌性痢疾','体格检查、血常规'),('宫颈疾病','宫颈筛查与日常预防')]:
            result,_=self.retrieve('久坐后肩颈不舒服，怎么调整习惯',title,content,.95)
            self.assertEqual(result['hits'],[])
            self.assertEqual(result['trace']['relevance_excluded'],1)

    def test_neck_habits_require_actionable_neck_content(self):
        self.assertFalse(directly_relevant('肩颈不适怎么调整习惯',
            {'metadata':{'title':'颈部解剖'},'content':'颈椎由七块椎骨组成。'}))
        self.assertEqual(contextualize_query('那脖子酸怎么办',[{'role':'user','content':'高血压'}]),
                         ('那脖子酸怎么办',False))

    def test_medication_boundary_still_precedes_retrieval(self):
        result,kb=self.retrieve('孩子布洛芬吃多少毫升','布洛芬','药物资料')
        self.assertEqual(result['status'],'needs_information')
        kb.milvus_client.search.assert_not_called()

    def test_other_colloquial_questions_are_not_blocked_by_missing_keyword(self):
        result,kb=self.retrieve('站了一天脚踝酸，怎么放松','脚踝护理','脚踝放松与休息')
        self.assertEqual(result['status'],'ok')
        kb.milvus_client.search.assert_called_once()

    def test_unrelated_programming_request_returns_zero_after_search(self):
        result,kb=self.retrieve('帮我写一段Python快速排序代码','药物资料','药物可以快速缓解症状',.9)
        self.assertEqual(result['hits'],[])
        kb.milvus_client.search.assert_called_once()

    def test_credit_only_and_trauma_do_not_support_work_habit_advice(self):
        for title,body in [('颈椎日常注意事项','审核：某医院 主任医师'),
                           ('颈椎损伤急救','受伤后应休息，不要随意搬动颈部。')]:
            self.assertFalse(directly_relevant('脖子酸，电脑前工作注意什么',
                             {'metadata':{'title':title},'content':title+'\n\n'+body}))

    def test_incidental_cold_tag_does_not_make_mastoid_article_relevant(self):
        self.assertFalse(directly_relevant('感冒了吃什么蔬菜',
            {'metadata':{'title':'急性乳突炎','topics':['感冒']},'content':'感冒后进行检查。'}))

    def test_credit_line_does_not_hide_following_substantive_content(self):
        self.assertTrue(directly_relevant('脖子酸，电脑前工作注意什么',
            {'metadata':{'title':'颈部护理'},'content':'颈部护理\n\n审核：某医师\n应当调整坐姿，避免颈部长期低头。'}))
