from chatchat.baidu import Chat

history = [
    {
        "role": "user",
        "content": "简单介绍一下你自己",
    },
    {
        "role": "assistant",
        "content": "我是人工智能助手，具备智能问答、自然语言处理等多项功能，致力于为用户提供准确、便捷的解答和服务。",
    }
]
chat = Chat(history=history)
r = chat.chat("说的再详细点！")
print(r)
r = chat.chat("给我举个具体的例子。")
print(r)
