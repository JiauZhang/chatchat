from chatchat.alibaba import Chat

chat = Chat('./data.json')
while True:
    user = input('user: ')
    r = chat.chat(user)
    message = r['output']['choices'][0]['message']
    print(f"{message['role']}: {message['content']}")
