import os, yaml

class Skill:
    def __init__(self, source):
        self.source = source
        self.load_skill()

    def load_skill(self):
        with open(os.path.join(self.source, 'SKILL.md'), 'r') as f:
            for line in f:
                if line.strip() == '---':
                    break
            lines = []
            for line in f:
                if line.strip() == '---':
                    break
                lines.append(line)
            metadata = ''.join(lines)
            lines.clear()
            for line in f:
                lines.append(line)
            instruction = ''.join(lines)

        self.metadata = yaml.safe_load(metadata)
        self.name = self.metadata['name']
        self.description = self.metadata['description']
        self.instruction = f'You must strictly follow the following skill rules to perform the task:\n\n{instruction}'
