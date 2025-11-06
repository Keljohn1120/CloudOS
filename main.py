from firebase import Firebase
from scheduling import Computer
from objects import User
from dotenv import load_dotenv
from threading import Thread

load_dotenv()

computer = Computer()
thread = Thread(target=computer.run, daemon=True)
thread.start()

fb = Firebase(computer)
user = fb.login("johnlloydunida0@gmail.com", "password")

#fb.upload_file(user, 'hotdog.txt', './test.txt')
#print(fb.get_owned_files(user))
#fb.update_file(user, 'documents/minecraft.txt', './test.txt')
#print(fb.get_file(user, 'hello.txt'))

cur_dir = []
while True:
    root = fb.get_owned_files(user)
    print(root)
    for directory in cur_dir:
        if (len(directory) > 1):
            root = root.get(directory, {})
    keys = [(key.replace("&123", "."), 'f' if 'type' in root.get(key, {}) else 'd') for key in root.keys()]
    print('='*50)
    for i, file in enumerate(keys):
        print(f'[{str(i)}] {file[0]} ({file[1]})')
    print('type "back" to go back...')
    choice = input(f'{user.localId}/{"/".join(cur_dir[1:])}>>>')
    
    if (choice in 'back'):
        if (len(cur_dir) == 0):
            break
        cur_dir.pop()
        continue
    if (not choice.isnumeric()):
        continue
    choice = int(choice)
    if (keys[choice][1] == 'd'):
        cur_dir.append(keys[choice][0])
    else:
        action = input("Do you want read (r) or delete (d) the file: ")
        if (action == 'd'):
            print("Deleting file in", f"users/{user.localId}/owned_files/"+"/".join(cur_dir))
            fb.delete_owned_file(user, keys[choice][0], "/".join(cur_dir))
        else:
            print(f'reading file {keys[choice][0]}')
            with open(fb.get_file(user, "/".join(cur_dir)+"/"+keys[choice][0]), 'r') as f:
                for line in f.readlines():
                    print(line, '\n')
            input("enter to continue...")
