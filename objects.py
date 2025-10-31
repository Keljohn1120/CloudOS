class User:
    localId:str
    idToken:str
    email:str
    password:str
    refreshToken:str


    def __init__(self, email:str, password:str):
        self.email = email
        self.password = password
    
    def setup_account(self, loginDetails:dict):
        self.localId = loginDetails.get('localId')
        self.refreshToken = loginDetails.get('refreshToken')
        self.idToken = loginDetails.get('idToken')


    