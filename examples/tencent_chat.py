from chatchat.tencent import Chat

chat = Chat('./data.json')
while True:
    user = input('user: ')
    r = chat.chat(user)
    message = r['Response']['Choices'][0]['Message']
    print(f"{message['Role']}: {message['Content']}")

