from objects import User
import google.auth.transport.requests
from google.oauth2 import service_account
from datetime import datetime
import logging
import requests
import math
import sys
import os

class Process:
    process_type:str = "process"
    burst_time:int = 0
    original_burst_time:int = 0
    sub_processed_time:int = 0
    sub_wait_time:int = 0
    process_id:int = 0
    completed_time:float

    def __init__(self, user:User, priority:int=3):
        self.user = user
        self.arrival_time = datetime.now().timestamp()
        self.priority = priority
        self.process_id = Process.process_id
        Process.process_id += 1

    
    def wait(self):
        self.sub_wait_time += 1
    
    def increase_priority(self):
        if (self.priority > 1):
            self.priority -= 1
            self.sub_wait_time = 0
    
    def decrease_priority(self):
        if (self.priority < 3):
            self.priority += 1
            self.sub_processed_time = 0

    def process(self):
        self.sub_processed_time += 1
        self.burst_time -= 1

    def is_completed(self) -> bool:
        return False


class DownloadProcess(Process):
    process_type:str = "download"
    download_size:int = 1024
    current_downloaded:int = 0
    completed:bool = False

    def __init__(self, download_link:str, user:User, file_name:str):
        super().__init__(user)
        self.download_link = download_link
        self.file_name = file_name
        try:
            with open(f'{os.environ.get("CACHE_PATH")}/{file_name}', 'wb') as f:
                f.write(b'')
        except FileNotFoundError:
            os.makedirs(f'{os.environ.get("CACHE_PATH")}/{"/".join(self.file_name.split("/")[:-1])}', exist_ok=True)
            with open(f'{os.environ.get("CACHE_PATH")}/{file_name}', 'wb') as f:
                f.write(b'')
        r = requests.get(self.download_link, headers={"Authorization": "Bearer "+self.user.idToken, "Range":f"bytes=0-0"})
        if (r.ok):
            total = r.headers.get("Content-Range").split("/")[1]
            self.burst_time = math.ceil(int(total) / self.download_size)
            self.original_burst_time = math.ceil(int(total) / self.download_size)

    def process(self):
        r = requests.get(self.download_link, headers={"Authorization": "Bearer "+self.user.idToken, "Range":f"bytes={self.current_downloaded}-{self.current_downloaded+self.download_size-1}"})
        if (r.ok):
            with open(f'{os.environ.get("CACHE_PATH")}/{self.file_name}', 'ab') as f:
                f.write(r.content)
            end, total = r.headers.get("Content-Range").split("-")[1].split("/")
            self.current_downloaded = int(end) + 1
            super().process()
            if (self.current_downloaded >= int(total)):
                self.completed = True
                self.completed_time = datetime.now().timestamp()
    
    def is_completed(self) -> bool:
        return self.completed


class UploadProcess(Process):
    process_type:str = "upload"
    upload_url:str
    upload_size:int = 262144
    current_uploaded:int = 0
    completed:bool = False
    creds = service_account.Credentials.from_service_account_file('./cloudos-12cdc-firebase-adminsdk-fbsvc-9b35e8b6ff.json', scopes=["https://www.googleapis.com/auth/devstorage.full_control"])

    def __init__(self, firebase_bucket:str, user:User, file_name:str, file:str):
        super().__init__(user)
        self.file_name = file_name
        self.firebase_bucket = firebase_bucket
        self.file = file
        self.file_size = os.path.getsize(file)
        self.burst_time = math.ceil(self.file_size / self.upload_size)
        self.original_burst_time = math.ceil(self.file_size / self.upload_size)
        self.creds.refresh(google.auth.transport.requests.Request())
        self.access_token = self.creds.token

        url = f"https://storage.googleapis.com/upload/storage/v1/b/{self.firebase_bucket}/o?uploadType=resumable&name=files/{user.localId}/{self.file_name}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "application/octet-stream",
        }
        result = requests.post(url, headers=headers)
        if (result.ok):
            self.upload_url = result.headers.get("Location")
        else:
            raise Exception("Failed to initiate upload session")

    def process(self):
        if (self.upload_url):
            with open(self.file, 'rb') as f:
                f.seek(self.current_uploaded)
                chunk = f.read(self.upload_size)
                if (not chunk):
                    self.completed = True
                    return
                headers = {
                    "Content-Length": str(self.upload_size),
                    "Content-Range": f"bytes {self.current_uploaded}-{self.current_uploaded + len(chunk) - 1}/{self.file_size}",
                    "Authorization": f"Bearer {self.access_token}"
                }

                result = requests.put(self.upload_url, headers=headers, data=chunk)
                if (result.ok or result.status_code == 308):
                    self.current_uploaded += len(chunk)
                    super().process()
                    if (self.current_uploaded >= self.file_size):
                        self.completed = True
                        self.completed_time = datetime.now().timestamp()
                    
    def is_completed(self) -> bool:
        return self.completed


class Computer:
    logger = logging.getLogger("Computer")
    multi_level_scheduling:dict[int, dict[str, list[Process]]] = {
        1:{"queue":[]}, #FCFS
        2:{"queue":[]}, #RR
        3:{"queue":[]}  #SRTF
    }
    settings:dict = {
        "aging_time":10,
        "time_quantum":3,
        "lower_priority_time":5
    }
    stats:list[tuple]
    current_process:Process = None
    start_time:int = 0

    def __init__(self):
        logging.basicConfig(handlers=[logging.FileHandler("output.log", 'w')])
        self.logger.setLevel(logging.DEBUG)
        self.stats = []
        self.stat_offset = 0

    def add_process(self, process:Process):
        self.multi_level_scheduling[process.priority]["queue"].append(process)
        self.logger.info(f"Process {process.process_id} type {process.process_type} added to priority {process.priority} queue.")

    def run(self):
        while True:
            #Resets stats every minute
            if (datetime.now().timestamp() - self.stat_offset >= 60 * 1):
                self.stats.clear()
                self.stat_offset = datetime.now().timestamp()

            #Waiting and Aging
            for priority in range(1, 4):
                for process in self.multi_level_scheduling[priority]["queue"]:
                    process.wait()
                    if (process.sub_wait_time >= self.settings.get("aging_time") and process.priority > 1):
                        process.increase_priority()
                        self.multi_level_scheduling[priority]["queue"].remove(process)
                        self.multi_level_scheduling[process.priority]["queue"].append(process)
                        self.logger.info(f"Process {process.process_id} type {process.process_type} aged to priority {process.priority}.")
            
            #Processing the current process
            if (self.current_process):
                self.current_process.process()
                if (self.current_process.is_completed()):
                    self.logger.info(f"Process {self.current_process.process_id} type {self.current_process.process_type} finished processing")
                    turn_around_time = self.current_process.completed_time - self.current_process.arrival_time
                    waiting_time = turn_around_time - self.current_process.original_burst_time
                    self.stats.append((self.current_process.arrival_time, turn_around_time, waiting_time))
                    self.current_process = self.select_from_mlfq()
                elif (self.current_process.priority == 3):
                    if (self.multi_level_scheduling[2]["queue"] or self.multi_level_scheduling[1]["queue"]):
                        self.logger.info(f"Process {self.current_process.process_id} type {self.current_process.process_type} preempted.")
                        if (self.current_process.sub_processed_time >= self.settings.get("lower_priority_time")):
                            self.current_process.decrease_priority()
                            self.logger.info(f"Process {self.current_process.process_id} type {self.current_process.process_type} lower to priority {self.current_process.priority}")
                        self.multi_level_scheduling[self.current_process.priority]["queue"].append(self.current_process)
                        self.current_process = self.select_from_mlfq()
                    elif (self.multi_level_scheduling[3]["queue"]):
                        self.multi_level_scheduling[3]["queue"].sort(key=lambda p: p.burst_time)
                        if (self.multi_level_scheduling[3]["queue"][0].burst_time < self.current_process.burst_time):
                            self.logger.info(f"Process {self.current_process.process_id} type {self.current_process.process_type} preempted.")
                            if (self.current_process.sub_processed_time >= self.settings.get("lower_priority_time")):
                                self.current_process.decrease_priority()
                                self.logger.info(f"Process {self.current_process.process_id} type {self.current_process.process_type} lower to priority {self.current_process.priority}")
                            self.multi_level_scheduling[self.current_process.priority]["queue"].append(self.current_process)
                            self.current_process = self.select_from_mlfq()
                elif (self.current_process.priority == 2):
                    if (self.current_process.sub_processed_time % self.settings.get("time_quantum") == 0):
                        self.logger.info(f"Process {self.current_process.process_id} type {self.current_process.process_type} time quantum expired.")
                        if (self.current_process.sub_processed_time >= self.settings.get("lower_priority_time")):
                            self.current_process.decrease_priority()
                            self.logger.info(f"Process {self.current_process.process_id} type {self.current_process.process_type} lower to priority {self.current_process.priority}")
                        self.multi_level_scheduling[self.current_process.priority]["queue"].append(self.current_process)
                        self.current_process = self.select_from_mlfq()
            else:
                self.current_process = self.select_from_mlfq()
    
    def select_from_mlfq(self) -> Process:
        for priority in range(1, 4):
            queue = self.multi_level_scheduling[priority]["queue"]
            if (len(queue) > 0):
                process = queue.pop(0)
                self.logger.info(f"Process {process.process_id} type {process.process_type} selected from priority {priority} queue.")
                process.sub_wait_time = 0
                return process
        return None


