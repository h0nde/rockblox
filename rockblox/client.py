from .input import press_key, release_key, bulk_press_and_release_key
from threading import Lock
from PIL import Image
import requests
import ctypes
import win32ui
import win32gui
import win32process
import win32con
import win32com.client
import subprocess
import time
import os
import win32api

client_lock = Lock() # used to limit certain interactions to one client at a time
shell = win32com.client.Dispatch("WScript.Shell") # setforeground needs this for some reason

def get_hwnd_for_pid(pid: int) -> int:
    def callback(hwnd, hwnds):
        if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid:
                hwnds.append(hwnd)
        return True
        
    hwnds = []
    win32gui.EnumWindows(callback, hwnds)
    return hwnds and hwnds[0]

class ClientMutex:
    """
    Takes control of the client mutex, allowing multiple clients to be open at the same time.
    Won't work if a client is already open before it is called.
    """
    
    def __init__(self):
        self.mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "ROBLOX_singletonMutex")

class Client:
    place_id: int
    job_id: str
    hwnd: int
    process: subprocess.Popen

    def __init__(self, session: 'Session', place_id: int, job_id: str=None,
        size: tuple=(100,100), client_path: str=None):
        if not session.id:
            raise("Session is not authenticated")
        self.session = session
        self.redeem_url = self.session.build_url(
            "www", "/Login/Negotiate.ashx")
        self.client_path = client_path or self.find_client_path()
        self.place_id = place_id
        self.job_id = job_id
        self.process = None
        self.hwnd = None
        self.launch()
        if size:
            self.resize(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
    
    def __repr__(self):
        return f"Client for {self.session}"

    """
    Launch the RobloxPlayerBeta.exe process, and wait for it's window to spawn
    """
    def launch(self):
        if self.process:
            raise Exception(".launch() has already been called")

        with self.session.request(
            method="POST",
            url=self.session.build_url(
                "auth", "/v1/authentication-ticket")
        ) as resp:
            auth_ticket = resp.headers["rbx-authentication-ticket"]
        
        self.process = subprocess.Popen([
            os.path.join(self.client_path, "RobloxPlayerBeta.exe"),
            "--play",
            "-a", self.redeem_url,
            "-t", auth_ticket,
            "-j", self.build_joinscript_url(),
            "-b", str(self.session.browser_id),
            f"--launchtime={int(time.time()*1000)}",
            "--rloc", "en_us",
            "--gloc", "en_us"
        ])

        start = time.time()
        while time.time()-start < 15:
            hwnd = get_hwnd_for_pid(self.process.pid)
            if hwnd:
                self.hwnd = hwnd
                break
        
        if not self.hwnd:
            self.close()
            raise TimeoutError("Timed out while getting window")

    def find_client_path(self) -> str:
        templates = [
            "C:\\Users\\{username}\\AppData\\Local\\Roblox\\Versions\\{version}",
            "C:\\Program Files (x86)\\Roblox\\Versions\\{version}",
            "C:\\Program Files\\Roblox\\Versions\\{version}",
        ]
        username = os.environ["USERPROFILE"].split("\\")[-1]
        with requests.get(self.session.build_url(
            "setup", "/version.txt", "http")
        ) as resp:
            version = resp.text.strip()

        for template in templates:
            path = template.format(
                username=username,
                version=version)
            if os.path.exists(path):
                return path

        raise FileNotFoundError("Could not find path to client")

    """
    Build joinscript URL based on initial parameters
    """
    def build_joinscript_url(self) -> str:
        pl_url = self.session.build_url(
            "assetgame", "/game/PlaceLauncher.ashx")
        if self.place_id and self.job_id:
            script_url = f"{pl_url}?request=RequestGameJob&browserTrackerId={self.session.browser_id}&placeId={self.place_id}&gameId={self.job_id}&isPlayTogetherGame=false"
        elif self.place_id:
            script_url = f"{pl_url}?request=RequestGame&browserTrackerId={self.session.browser_id}&placeId={self.place_id}&isPlayTogetherGame=false"
        return script_url

    """
    Waits until the client is past the loading screen.
    """
    def wait_for(self, timeout: float=15, check_interval: float=0.25,
        ignored_colors: list=[(45, 45, 45), (0, 0, 0)]):
        start = time.time()
        
        while time.time()-start < timeout:
            screenshot = self.screenshot()
            px_count = screenshot.size[0]*screenshot.size[1]
            dominant_color = sorted(
                screenshot.getcolors(px_count),
                key=lambda t: t[0])[-1][1]
            if not dominant_color in ignored_colors:
                return
            time.sleep(check_interval)
        
        raise TimeoutError("Timed out while loading")

    """
    Kill the client process
    """
    def close(self):
        self.process.kill()

    """
    Focus the client window
    """
    def focus(self):
        if ctypes.windll.user32.GetActiveWindow() == self.hwnd:
            return
        shell.SendKeys('%')
        win32gui.SetForegroundWindow(self.hwnd)

    """
    Resize the client window
    """
    def resize(self, size):
        with client_lock:
            win32gui.MoveWindow(self.hwnd, *win32gui.GetWindowRect(self.hwnd)[:2], *size, True)

    """
    Get client window size
    """
    def size(self, xo=0, yo=0) -> tuple:
        rect = win32gui.GetWindowRect(self.hwnd)
        x = rect[0]
        y = rect[1]
        w = rect[2] - x
        h = rect[3] - y
        return (w-xo, h-yo)
    
    """
    Captures a `PIL.Image` screenshot of the client window
    """
    def screenshot(self, crop=True) -> Image:
        dc_handle = win32gui.GetWindowDC(self.hwnd)
        dcObj=win32ui.CreateDCFromHandle(dc_handle)
        cDC=dcObj.CreateCompatibleDC()
        dataBitMap = win32ui.CreateBitmap()
        dataBitMap.CreateCompatibleBitmap(dcObj, *self.size())
        cDC.SelectObject(dataBitMap)
        cDC.BitBlt((0,0),self.size(), dcObj, (0,0), win32con.SRCCOPY)
        bmpinfo = dataBitMap.GetInfo()
        bmpstr = dataBitMap.GetBitmapBits(True)
        im = Image.frombuffer(
            'RGB',
            (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
            bmpstr, 'raw', 'BGRX', 0, 1)
        dcObj.DeleteDC()
        cDC.DeleteDC()
        win32gui.DeleteObject(dataBitMap.GetHandle())
        win32gui.ReleaseDC(self.hwnd, dc_handle)
        if crop:
            im = im.crop((11,45, *self.size(11, 11)))
        return im

    """
    Press(hold) single key
    """
    def press_key(self, k):
        with client_lock:
            self.focus()
            press_key(k)
     
    """
    Release single key
    """
    def release_key(self, k):
        with client_lock:
            self.focus()
            release_key(k)
      
    """
    Attempts to write and send a chat message by simulating keystrokes
    """
    def chat_message(self, message: str):
        with client_lock:
            self.focus()
            win32api.SendMessage(self.hwnd, win32con.WM_CHAR, ord("/"), 0)
            time.sleep(0.1)
            for c in message:
                win32api.SendMessage(self.hwnd, win32con.WM_CHAR, ord(c), 0)
            time.sleep(0.1)
            press_key(0x0D)
            release_key(0x0D)
