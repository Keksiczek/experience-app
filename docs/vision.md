# Produktová vize

## Základní myšlenka

Experience-app není další mapová aplikace. Je to nástroj pro „duševní cestování" — z volného textového promptu sestaví kurátorovanou sekvenci reálných míst, která společně tvoří smysluplný geo-příběh.

Uživatel neoznačuje místa na mapě. Zadá záměr. Aplikace za něj kurátoruje výběr.

## Co aplikace řeší

Existující nástroje (Google Maps, komoot, Wikiloc) vyžadují, aby uživatel věděl, co hledá — konkrétní místo, trasu nebo typ aktivity. Experience-app cílí na opačný případ: uživatel ví jen jak chce, aby se mu místo cítilo, ne kde je.

Příklady promptů:
- „opuštěné průmyslové oblasti s historií těžby uhlí"
- „drsná horská sedla s výhledem přes hranici"
- „samotářský roadtrip po poušti, žádní turisté"
- „vesnice v Alpách s dramatickou krajinou a minimální infrastrukturou"

## Hodnota produktu

Hodnota není v mapě samotné, ale v procesu kurátorování:

1. Prompt je převeden na strukturovaný intent
2. Intent je matchován na reálné lokality z ověřitelných open dat
3. Lokality jsou obohaceny o dostupná média (street-level fotografie, geotagované obrázky)
4. Výsledek je sekvence zastávek s kontextem — ne jen seznam souřadnic

## Zásadní produktové principy

### 1. Žádná halucinace faktů
Každý detail v naraci musí být podložen strukturovanými daty. Pokud nejsou data k dispozici, aplikace to přizná. „Nemáme fotografii tohoto místa" je přijatelný výstup. Vymyšlená popisná věta není.

### 2. Kontrolovaná degradace
Aplikace musí fungovat i s nekvalitními nebo chybějícími daty. Každá zastávka nese `fallback_level` — signál o tom, jak moc se musela pipeline spoléhat na slabší zdroje. Uživatel může vidět, které zastávky jsou „podložené" a které jsou jen „best guess".

### 3. Debuggovatelnost
Každý krok pipeline loguje vstupy, výstupy a důvody rozhodnutí. Vývojář musí být schopen dohledat, proč pipeline vybrala konkrétní místo nebo proč fallbackla.

### 4. Lean první iterace
První verze není finální produkt. Je to spike: ověření, zda pipeline dokáže sestavit použitelné experience z open dat. Neřešíme video, simulaci jízdy, globální spolehlivost ani UI.

## Co první iterace neřeší

- Plná globální coverage dat
- Video nebo simulace jízdy
- Personalizace na základě historických preferencí
- Real-time data (počasí, dostupnost)
- Frontend (první verze je API-only)
- Microservices nebo horizontální škálování

## Cílový uživatel (první iterace)

Vývojář nebo kurátor, který testuje pipeline přes API. Chceme ověřit, zda výstup dává smysl, než začneme řešit UX.

## Měřítka úspěchu pro první iteraci

- Pipeline zvládne sestavit experience pro alespoň jeden z 3 fixních módů v libovolném testovacím regionu
- Každá zastávka má alespoň `place_id`, `lat`, `lon` a `why_here`
- Fallback chain je čitelný v logu
- Výsledek neobsahuje žádné halucinované detaily
