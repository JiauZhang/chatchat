from chatchat.zhipu import Chat

chat = Chat(model='glm-3-turbo')
while True:
    user = input('user: ')
    r = chat.chat(user)
    message = r['choices'][0]['message']
    print(f"{message['role']}: {message['content']}")
