# Render every simulator screen at 1440x900 into verify/out/mock/<id>.png
from playwright.sync_api import sync_playwright
import re, os
html=open('platform-mockup.html').read()
ids=re.findall(r'<section class="screen" data-screen="([^"]+)"', html)
url='file:///home/user/deployment-hacohen/digital-office/platform-mockup.html'
os.makedirs('verify/out/mock',exist_ok=True)
with sync_playwright() as p:
    b=p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    pg=b.new_page(viewport={'width':1440,'height':900})
    pg.goto(url, wait_until='load', timeout=30000)
    pg.add_style_tag(content='#navBtn{display:none!important}')
    # freeze the live clock so diffs are stable (stop the tick interval)
    pg.evaluate("()=>{for(let i=1;i<99999;i++)clearInterval(i);}")
    for s in ids:
        try:
            pg.evaluate("id=>window.go(id)", s); pg.wait_for_timeout(120)
            pg.screenshot(path=f'verify/out/mock/{s}.png')
        except Exception as e: print('ERR',s,e)
    b.close()
print('rendered', len(ids))
