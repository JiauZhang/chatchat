class Agent:
    def __init__(self, model, instruction):
        self.model = model
        self.model.instruction = instruction

    def __call__(self, text, generation_options={}):
        return self.model.chat(text, generation_options=generation_options)
