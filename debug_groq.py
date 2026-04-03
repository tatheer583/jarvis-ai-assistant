from groq import Groq
from dotenv import dotenv_values

env = dotenv_values('.env')
client = Groq(api_key=env.get('GroqAPIKey', ''))
completion = client.chat.completions.create(
    model='llama-3.3-70b-versatile',
    messages=[{'role':'system','content':'You are helpful.'},{'role':'user','content':'Say hi'}],
    max_tokens=64,
    temperature=0.7,
    top_p=1,
    stream=False,
)
msg = completion.choices[0].message
print(type(msg))
print(msg)
print('has content', hasattr(msg, 'content'))
print('has get', hasattr(msg, 'get'))
print('dir', [a for a in dir(msg) if not a.startswith('_')])
if hasattr(msg, 'content'):
    print('content value', msg.content)
if isinstance(msg, dict):
    print('dict', msg)
