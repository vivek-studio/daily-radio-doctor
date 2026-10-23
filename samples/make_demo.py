import random, datetime as dt
random.seed(7)
camps=["Holiday Core","Holiday Cyber Week","Q4 Frag","Jan Skincare Daily Deals","Korean Skincare Promo","Lash Day 2027","Moisturizers MBC","Spring Beauty Event","Summer Fridays"]
rows=[];d=dt.date(2025,10,1);end=dt.date(2026,10,23);prev=[]
out=[]
while d<=end:
    if d.weekday()<5 and random.random()>0.04:
        n=random.randint(0,6);items=[]
        for _ in range(n):
            nm=f"{random.choice(camps)} {random.choice(['Bun','Der'])} {random.choice('ABCDE')}"
            st=random.choice(["RD1","RD2","RD3","Final handoff","Additional Revisions 2","KO Ques"])
            a=random.choice([None,None,5,12,18,22,35,52,61,85,103,216])
            items.append((nm,st,a,random.random()<.25))
        hdr=f"@here {d.day:02d} {d.strftime('%B')}, {d.year} Project Status\nSEPHORA\n"
        if d<dt.date(2026,6,1):
            L=[];
            for i,(nm,st,a,am) in enumerate(items,1):
                t=f"{nm} - {st} due today" if st!="KO Ques" else f"{nm} - KO questions due today"
                if a: t+=f" ({a} assets)"
                if am: t+=" (AM HO)"
                if prev and random.random()<.15: t=f"~~{t}~~"
                L.append(f"{i}. {t}")
            L+= [f"{len(L)+1}. {random.choice(camps)} Bun A - Feedback awaited by 10/3 (35 assets)"]
            out.append(hdr+"Design\n\n"+"\n".join(L)+"\n————————\nCopy\n\n"+"\n".join(L)+"\n—————————\nWRIKE RESPONSES\n——————————\nSLACK RESPONSES\n")
        else:
            L=[]
            for i,(nm,st,a,am) in enumerate(items,1):
                t=f"{nm} - {st}" if st!="KO Ques" else f"{nm} - KO Ques - RD1 tentatively due on 10/30"
                if a: t+=f" ({a} assets)"
                if am: t+=" (AM HO)"
                if prev and random.random()<.15: t=f"~~{t}~~"
                L.append(f"{i}. {t}")
            out.append(hdr+"\nDUE TODAY\n\n"+("\n".join(L) or "1. NA")+"\n\nPROJECTS KICKING OFF\n\n1. NA\n\nIN PIPELINE\n\n1. Foo Bun A - RD1 due on 10/26 (52 assets)\n\nFEEDBACK AWAITED\n\n1. Bar Der E - Feedback awaited by 10/26 (2 assets)\n")
        prev=items
    d+=dt.timedelta(days=1)
open("samples/demo_year.txt","w").write("\n".join(out))
