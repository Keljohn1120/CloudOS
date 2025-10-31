from firebase import Firebase
from objects import User


fb = Firebase()
user = fb.login("johnlloydunida0@gmail.com", "password")

#fb.upload_file(user, './test.txt', 'documents/minecraft.txt')
#print(fb.get_owned_file_ids(user))
#fb.update_file(user, '5321fa28-7', './test.txt')
#print(fb.get_file(user, '3a73ed1a-7'))

cur_dir = ['.']
while True:
    root = fb.get_owned_file_ids(user).get('users').get(user.localId).get('owned_files')
    for directory in cur_dir:
        if (len(directory) > 1):
            root = root.get(directory, {})
    keys = [(key, 'f' if 'type' in root.get(key, {}) else 'd') for key in root.keys()]
    print('='*50)
    for i, file in enumerate(keys):
        print(f'[{str(i)}] {file[0]} ({file[1]})')
    print('type "back" to go back...')
    choice = input('>>>')
    
    if (choice in 'back'):
        cur_dir.pop()
        if (len(cur_dir) == 0):
            break
        continue
    if (not choice.isnumeric()):
        continue
    choice = int(choice)
    if (keys[choice][1] == 'd'):
        cur_dir.append(keys[choice][0])
    else:
        print(f'reading file {keys[choice][0]}')
        with open(fb.get_file(user, keys[choice][0]), 'r') as f:
            for line in f.readlines():
                print(line, '\n')
        input("enter to continue...")
