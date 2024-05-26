from chatchat.alibaba import Chat

chat = Chat()
while True:
    user = input('user: ')
    r = chat.chat(user)
    message = r['output']['choices'][0]['message']
    print(f"{message['role']}: {message['content']}")
