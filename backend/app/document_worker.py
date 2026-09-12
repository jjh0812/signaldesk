"""Isolated, network-free text extractor. pypdf is locally vendored under its BSD license."""
import json,sys,re
from pathlib import Path

def main():
    if len(sys.argv)!=4:return 2
    source,out,mime=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
    if source.stat().st_size>6*1024*1024:return 3
    # POSIX address-space cap; Windows uses subprocess timeout (no hard memory sandbox).
    if sys.platform!='win32':
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    if mime=='application/pdf':
        sys.path.insert(0,str(Path(__file__).with_name('_vendor')/'pypdf_5_9_0.zip'))
        from pypdf import PdfReader
        reader=PdfReader(str(source),strict=False)
        if reader.is_encrypted:return 4
        total=len(reader.pages)
        # Read every page for ordinary short transcripts. For long filings retain
        # first 80 and last 20 pages and explicitly label the truncation.
        indices=list(range(total)) if total<=100 else list(range(80))+list(range(total-20,total))
        pages=[];budget=900_000;truncated=total>100
        for i in indices:
            text=reader.pages[i].extract_text() or ''
            if len(text)>budget:truncated=True
            text=text[:budget];budget-=len(text)
            pages.append({'page':i+1,'text':text})
            if budget<=0:truncated=True;break
    else:
        # Only text extraction; never execute page scripts or fetch linked resources.
        from html.parser import HTMLParser
        class Extract(HTMLParser):
            def __init__(self):super().__init__();self.skip=0;self.parts=[]
            def handle_starttag(self,tag,attrs):
                if tag in ('script','style','noscript','svg'):self.skip+=1
                elif tag in ('p','div','li','h1','h2','h3','tr','br'):self.parts.append('\n')
            def handle_endtag(self,tag):
                if tag in ('script','style','noscript','svg'):self.skip=max(0,self.skip-1)
                elif tag in ('p','div','li','tr'):self.parts.append('\n')
            def handle_data(self,data):
                if not self.skip:self.parts.append(data)
        data=source.read_bytes().decode('utf-8',errors='replace')
        if mime!='text/plain':
            parser=Extract();parser.feed(data);data=' '.join(parser.parts)
        total=1;truncated=len(data)>900_000;pages=[{'page':1,'text':data[:900_000]}]
    out.write_text(json.dumps({'pages':pages,'pages_total':total,'truncated':truncated},ensure_ascii=False),encoding='utf-8')
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:raise SystemExit(5)
