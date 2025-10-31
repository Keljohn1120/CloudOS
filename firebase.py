import pyrebase
from objects import User
from datetime import datetime
import uuid
import os
import json

firebaseConfig = {
  "apiKey": "AIzaSyC_DMlTx9Ipc9yx9IPA3lVeITXZD0QhwpE",
  "authDomain": "cloudos-12cdc.firebaseapp.com",
  "databaseURL": "https://cloudos-12cdc-default-rtdb.asia-southeast1.firebasedatabase.app",
  "projectId": "cloudos-12cdc",
  "storageBucket": "cloudos-12cdc.firebasestorage.app",
  "messagingSenderId": "710107657823",
  "appId": "1:710107657823:web:5d2104048a1587b84b4dea",
  "measurementId": "G-VCE7XX9FMR"
}

class Firebase:
    fb = pyrebase.initialize_app(firebaseConfig)
    auth = fb.auth()
    db = fb.database()
    storage = fb.storage()

    def login(self, email:str, password:str) -> User:
        result = self.auth.sign_in_with_email_and_password(email, password)
        user = User(email, password)
        user.setup_account(result)
        return user
    
    def register(self, user:User):
        result = self.auth.create_user_with_email_and_password(user.email, user.password)
        user.setup_account(result)
    
    def upload_file(self, user:User, file_path:str, cloud_path:str):
        path = ['users', user.localId, 'owned_files']
        path.extend(cloud_path.split("/"))
        file_name = path.pop().replace(".", "#123")
        unique_id = str(uuid.uuid4())[:10]
        self.storage.child(f'files/{unique_id}').put(file_path, token=user.idToken)

        root = self.db
        files = self.get_owned_file_ids(user)
        for directory in path:
            if (len(directory) > 1 and 'type' not in files):
                root = root.child(directory)
                files = files.get(directory, {})
        files[unique_id] = {'type':'file'}
        root.set(files, token=user.localId)

        self.db.child('files').child(unique_id).set({'name':file_name, 'meta':{'modified':datetime.now().isoformat()}}, token=user.localId)
    
    def get_owned_file_ids(self, user:User) -> dict:
        files = self.db.get(token=user.idToken).val()
        return files if (files) else {}

    def get_access_list_ids(self, user:User) -> list[str]:
        files = self.db.child('users').child(user.localId).child('access_list').get(token=user.idToken).val()
        return files if (files) else []

    def update_file(self, user:User, file_id:str, file_path:str):
        self.storage.child(f'files/{file_id}').put(file_path, token=user.idToken)
        self.db.child('files').child(file_id).child('meta').update({'modified':datetime.now().isoformat()}, token=user.idToken)
    
    def get_file(self, user:User, file_id:str) -> str:
        file = self.db.child('files').child(file_id).get(token=user.idToken).val()
        if (not file):
            return None
        file_name = file.get('name', "").replace("#123", ".")
        
        try:
            with open(f"./file_cache./{file_id}/details.json", 'r') as f:
                cache_meta:dict = json.loads(f.read())
        except FileNotFoundError:
            cache_meta = {}
        
        if (file_id not in os.listdir('./file_cache')):
            print('file is not yet downloaded')
            os.mkdir(f"./file_cache/{file_id}")
        
        if (cache_meta.get("modified") != file.get('meta', {}).get('modified', '')):
            print('file is outdated')
            with open(f'./file_cache/{file_id}/details.json', 'w') as f:
                f.write(json.dumps(file.get("meta")))
            self.storage.child(f'files/{file_id}').download(f'./file_cache/{file_id}', f'./file_cache/{file_id}/{file_name}', token=user.idToken)
        return f"./file_cache/{file_id}/{file_name}"

