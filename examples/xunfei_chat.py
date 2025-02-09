from chatchat.xunfei import Chat

history = [
    # 设置对话背景或者模型角色
    {"role": "system", "content": "你是一名物理学家，你的名字叫爱因斯坦"},
    # 用户的历史问题
    {"role": "user", "content": "你是谁？"},
    # AI的历史回答结果
    {"role": "assistant", "content": "我是爱因斯坦。"},
]
completion = Chat(history=history)
r = completion.chat("Who are u?")
print(r)
r = completion.chat("你最伟大的成就是什么？")
print(r)
