import requests
2
import re
3
 
4
# IDs de exemplo - acrescenta mais conforme fores descobrindo
5
COMMODITIES = {
6
"Helium-3": 10491,
7
}
8
 
9
produto = input("Produto: ").strip()
10
 
11
if produto not in COMMODITIES:
12
print(f"Produto '{produto}' ainda não está mapeado.")
13
exit()
14
 
15
commodity_id = COMMODITIES[produto]
16
 
17
url = f"https://inara.cz/elite/commodity/{commodity_id}/"
18
 
19
try:
20
html = requests.get(
21
url,
22
headers={
23
"User-Agent": "Mozilla/5.0"
24
},
25
timeout=30
26
).text
27
 
28
media = re.search(
29
r"Avg sell price.*?([\d,]+)\s*Cr",
30
html,
31
re.IGNORECASE | re.DOTALL
32
)
33
 
34
maximo = re.search(
35
r"Max sell price.*?([\d,]+)\s*Cr",
36
html,
37
re.IGNORECASE | re.DOTALL
38
)
39
 
40
print("\nResultado")
41
print("-" * 40)
42
 
43
if media:
44
print(f"Média: {media.group(1)} Cr")
45
else:
46
print("Média: não encontrada")
47
 
48
if maximo:
49
print(f"Máximo: {maximo.group(1)} Cr")
50
else:
51
print("Máximo: não encontrado")
52
 
53
except Exception as e:
54
print(f"Erro: {e}")