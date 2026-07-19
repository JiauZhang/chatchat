import os, yaml, re
from dataclasses import dataclass
from glob import glob

__skills_instruction_template__ = """## Skills System (Progressive Disclosure) 

### Available Skills

{skills_list}

### How to Use Skills

1. Check if a skill applies to the user's task
2. Read the skill's full instructions via `read_file`
3. Use absolute paths for skill helper scripts and configs, or reference docs
4. Follow the skill's workflow to complete the task"""


@dataclass
class Skill:
    name: str
    description: str
    path: str


class Skills:
    def __init__(self, sources=None):
        self.sources = sources or []
        self.skills = []

        for source in self.sources:
            for skill_md_path in glob(os.path.join(source, '**', 'SKILL.md'), recursive=True):
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
                if match:
                    frontmatter = yaml.safe_load(match.group(1))
                    self.skills.append(Skill(
                        name=frontmatter['name'],
                        description=frontmatter['description'],
                        path=os.path.abspath(skill_md_path),
                    ))

    def __bool__(self):
        return bool(self.skills)

    @property
    def instruction(self):
        if not self.skills:
            return ""
        skills_list = '\n'.join(f"- **{s.name}**: {s.description}\n  -> Read `{s.path}` for full instructions" for s in self.skills)
        return __skills_instruction_template__.format(skills_list=skills_list)
