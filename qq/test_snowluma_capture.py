"""Local QQ capture/launcher regression; no real account, windows or subprocess."""
import ctypes
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
from PIL import Image
from qq.snowluma import SnowLumaHost, _capture_qq_png


class WindowApi:
    def __init__(self, login=True):
        self.titles={1:'QQ - unrelated app',2:'QQ'}
        if login:self.titles[3]='QQ 登录'
    def SetProcessDPIAware(self):pass
    def IsWindowVisible(self, hwnd):return True
    def IsIconic(self, hwnd):return False
    def GetWindowTextLengthW(self, hwnd):return len(self.titles[hwnd])
    def GetWindowTextW(self, hwnd, buffer, size):buffer.value=self.titles[hwnd]
    def GetWindowRect(self, hwnd, pointer):
        r=pointer._obj
        r.left=r.top=0
        r.right,r.bottom=(1000,700) if hwnd==2 else (460,600)
        return True
    def EnumWindows(self, callback, data):
        for hwnd in self.titles:callback(hwnd,data)


class CaptureTests(unittest.TestCase):
    def capture(self, login):
        with patch.object(ctypes,'windll',SimpleNamespace(user32=WindowApi(login)),create=True), \
             patch.object(ctypes,'WINFUNCTYPE',ctypes.CFUNCTYPE,create=True), \
             patch('qq.snowluma._is_qq_window',side_effect=lambda hwnd: hwnd!=1), \
             patch('PIL.ImageGrab.grab',return_value=Image.new('RGB',(460,600),'white')) as grab:
            result=_capture_qq_png()
            return result,grab.call_args_list
    def test_capture_targets_login_window_handle_not_desktop_rectangle(self):
        result,calls=self.capture(True)
        self.assertTrue(result.startswith(b'\x89PNG'))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0].kwargs,{'window':3})
    def test_main_chat_and_unrelated_apps_are_not_captured(self):
        result,calls=self.capture(False)
        self.assertIsNone(result)
        self.assertEqual(calls,[])
    def test_hook_connection_timeout_is_not_reported_as_unfinished_scan(self):
        host=SnowLumaHost(install='unused')
        with patch.object(host,'_ensure_qq_process'), \
             patch.object(host,'_processes',return_value=[{'pid':1,'status':'connecting','injected':True,'connected':False}]), \
             patch.object(host,'capture',return_value=None), \
             patch('qq.snowluma.time.monotonic',side_effect=[0,1,2,151]), \
             patch('qq.snowluma.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'SnowLuma.*QQ'):
                host._wait_until_online(lambda:False,lambda image:None)
    def test_separate_node_path_is_used_without_changing_global_path(self):
        with TemporaryDirectory() as d:
            host=SnowLumaHost(install=Path(d)/'install',runtime=Path(d)/'runtime')
            process=Mock();process.poll.return_value=None
            with patch.dict('os.environ',{'MEDIX_SNOWLUMA_NODE':'C:/local-node/node.exe'}), \
                 patch.object(host,'_healthy',side_effect=[False,True]), \
                 patch.object(host,'_password',return_value='synthetic-test-password'), \
                 patch('qq.snowluma.subprocess.Popen',return_value=process) as launch:
                host._ensure_running()
                self.assertEqual(launch.call_args.args[0][0],'C:/local-node/node.exe')
                self.assertEqual(launch.call_args.kwargs['cwd'],str(host.runtime))
            host._process=None

if __name__=='__main__':unittest.main()
