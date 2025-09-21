from chatchat.tencent import Chat

chat = Chat()
while True:
    user = input('user: ')
    r = chat.chat(user)
    message = r['choices'][0]['message']
    print(f"{message['role']}: {message['content']}")
