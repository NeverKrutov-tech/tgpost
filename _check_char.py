from PIL import Image

img = Image.open("data/anekdotik_character.png")
w, h = img.size
px = img.load()
print(f"v6: {w}x{h}, Mode: {img.mode}")
bbox = img.getbbox()
print(f"Bbox: {bbox}")

# Color analysis on non-transparent pixels
samples = [(x,y) for x in range(0,w,3) for y in range(0,h,3)]
total = len(samples)

yellow = sum(1 for x,y in samples if px[x,y][3] > 10 and px[x,y][0] > 170 and px[x,y][1] > 130 and px[x,y][2] < 120)
brown_skin = sum(1 for x,y in samples if px[x,y][3] > 10 and 60 < px[x,y][0] < 150 and 30 < px[x,y][1] < 100 and px[x,y][2] < 70)
dark = sum(1 for x,y in samples if px[x,y][3] > 10 and px[x,y][0] < 50 and px[x,y][1] < 50 and px[x,y][2] < 50)
blue = sum(1 for x,y in samples if px[x,y][3] > 10 and px[x,y][2] > 80 and px[x,y][0] < 130 and px[x,y][1] < 150)
green = sum(1 for x,y in samples if px[x,y][3] > 10 and px[x,y][1] > 100 and px[x,y][0] < 100 and px[x,y][2] < 100)
gold = sum(1 for x,y in samples if px[x,y][3] > 10 and px[x,y][0] > 180 and px[x,y][1] > 140 and px[x,y][2] < 60)
white = sum(1 for x,y in samples if px[x,y][3] > 10 and px[x,y][0] > 200 and px[x,y][1] > 200 and px[x,y][2] > 200)

nontrans = sum(1 for x,y in samples if px[x,y][3] > 10)

print(f"\nNon-transparent pixels: {nontrans}/{total}")
print(f"\nColor analysis (of non-transparent):")
print(f"  Yellow (minion body):  {yellow} ({100*yellow//max(nontrans,1)}%)")
print(f"  Brown (dark skin):     {brown_skin} ({100*brown_skin//max(nontrans,1)}%)")
print(f"  Blue (overalls):       {blue} ({100*blue//max(nontrans,1)}%)")
print(f"  Dark (goggle/outlines):{dark} ({100*dark//max(nontrans,1)}%)")
print(f"  Green (bandana):       {green} ({100*green//max(nontrans,1)}%)")
print(f"  Gold (chain):          {gold} ({100*gold//max(nontrans,1)}%)")
print(f"  White:                 {white} ({100*white//max(nontrans,1)}%)")

print(f"\nHybrid checklist:")
print(f"  Yellow minion body?        {'YES' if yellow > nontrans*0.05 else 'NO'}")
print(f"  Dark brown skin (CJ)?      {'YES' if brown_skin > nontrans*0.03 else 'NO'}")
print(f"  Blue overalls?             {'YES' if blue > nontrans*0.03 else 'NO'}")
print(f"  Single goggle eye (dark)?  {'YES' if dark > nontrans*0.05 else 'NO'}")
print(f"  Green bandana?             {'YES' if green > nontrans*0.01 else 'NO'}")
print(f"  Gold chain?                {'YES' if gold > nontrans*0.01 else 'NO'}")
