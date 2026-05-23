import sys
sys.stdout.reconfigure(encoding='utf-8')
with open('tmp_original_reviewer.py','rb') as f:
    raw = f.read()
text = raw.decode('utf-16-le')
if text.startswith('\ufeff'):
    text = text[1:]
print('Decoded OK, length:', len(text))
with open('dts_agent/review/reviewer.py','w',encoding='utf-8') as f:
    f.write(text)
print('Written')
