from chatchat.google import Chat

chat = Chat()
while True:
    user = input('user: ')
    r = chat.chat(user)
    if r.text is None:
        print(r)
    else:
        print(f"assistant: {r.text}")
