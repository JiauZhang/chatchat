class Agent:
    def __init__(self, model, instruction):
        self.model = model
        self.model.instruction = instruction

    def __call__(self, text, stream=False, generation_kwargs={}):
        return self.model.chat(text, stream=stream, generation_kwargs=generation_kwargs)
