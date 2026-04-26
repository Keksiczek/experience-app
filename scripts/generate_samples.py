"""Generate curated sample experiences for the discover landing page.

Produces JSON files under ``data/samples/curated/`` matching the Experience
schema, plus the curator-only fields ``slug`` / ``title`` / ``teaser`` /
``cover_image`` consumed by ``GET /samples``.

Usage::

    cd backend && source .venv/bin/activate
    python ../scripts/generate_samples.py

Re-run after schema changes to keep samples in sync.  Samples are checked
into the repo so the home page always has content.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Resolve repo paths regardless of where the script is invoked from.
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
sys.path.insert(0, str(_REPO / "backend"))

from app.models.experience import (  # noqa: E402
    Experience,
    ExperienceQualityMetrics,
    ExperienceStop,
    GenerationMetadata,
    JobStatus,
)
from app.models.media import FallbackLevel  # noqa: E402

OUT_DIR = _REPO / "data" / "samples" / "curated"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _stop(
    *,
    order: int,
    place_id: str,
    name: str,
    short_title: str,
    lat: float,
    lon: float,
    why_here: str,
    narration: str,
    media_id: str | None = None,
    wikipedia_summary: str | None = None,
    wikipedia_url: str | None = None,
    wikipedia_lang: str | None = "cs",
) -> ExperienceStop:
    return ExperienceStop(
        id=str(uuid.uuid4()),
        order=order,
        stop_order=order - 1,
        place_id=place_id,
        media_id=media_id,
        lat=lat,
        lon=lon,
        name=name,
        short_title=short_title,
        why_here=why_here,
        narration=narration,
        fallback_level=FallbackLevel.FULL if media_id else FallbackLevel.NO_MEDIA,
        score=0.85,
        narration_confidence=0.78,
        decision_reasons=["curated sample"],
        grounding_sources=[wikipedia_url] if wikipedia_url else [],
        wikipedia_summary=wikipedia_summary,
        wikipedia_url=wikipedia_url,
        wikipedia_lang=wikipedia_lang if wikipedia_summary else None,
    )


def _experience(
    *,
    slug: str,
    title: str,
    teaser: str,
    cover_image: str,
    prompt: str,
    region: str,
    summary: str,
    route_style: str,
    stops: list[ExperienceStop],
) -> dict:
    now = datetime.now(UTC)
    fallback_distribution: dict[str, int] = {}
    for s in stops:
        fallback_distribution[s.fallback_level.value] = (
            fallback_distribution.get(s.fallback_level.value, 0) + 1
        )

    metadata = GenerationMetadata(
        started_at=now,
        completed_at=now,
        pipeline_steps=[
            "intent_parser",
            "region_discovery",
            "place_discovery",
            "media_resolution",
            "experience_composer",
            "narrator",
            "wikipedia_enrichment",
        ],
        provider_calls={"curated": 1},
        warnings=[],
        decision_reasons=[f"curated sample seeded from script ({slug})"],
        route_style_used=route_style,
        route_coherence_applied=route_style in {"linear", "loop"},
    )

    coverage = sum(1 for s in stops if s.media_id) / len(stops) if stops else 0.0
    metrics = ExperienceQualityMetrics(
        narration_confidence=sum(s.narration_confidence for s in stops) / len(stops),
        route_coherence_score=0.85 if route_style in {"linear", "loop"} else 0.55,
        imagery_coverage_ratio=coverage,
        diversity_score=0.75,
        fallback_distribution=fallback_distribution,
        context_richness=0.7,
    )

    exp = Experience(
        id=f"sample-{slug}",
        job_status=JobStatus.COMPLETED,
        prompt=prompt,
        selected_region=region,
        summary=summary,
        stops=stops,
        generation_metadata=metadata,
        quality_metrics=metrics,
        created_at=now,
    )

    payload = exp.model_dump(mode="json")
    payload["slug"] = slug
    payload["title"] = title
    payload["teaser"] = teaser
    payload["cover_image"] = cover_image
    return payload


# ── Curator-defined samples ─────────────────────────────────────────────────

SAMPLES: list[dict] = []


SAMPLES.append(
    _experience(
        slug="silesia-industrial-ruins",
        title="Průmyslové ruiny Horního Slezska",
        teaser=(
            "Šest pozůstatků těžkého průmyslu mezi Bytomem a Rudou Śląską — "
            "huty, šachty, cihelny, vše během jednoho dne autem."
        ),
        cover_image=(
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            "Huta_Pok%C3%B3j_w_Rudzie_%C5%9Al%C4%85skiej.jpg?width=600"
        ),
        prompt="opuštěné průmyslové oblasti v Horním Slezsku",
        region="Upper Silesia",
        summary=(
            "Trasa propojuje šest klíčových reliktů těžkého průmyslu Horního "
            "Slezska — od huty Pokój, kde se válcoval ocelový plech pro celý "
            "Reich, až k zarostlé hutě Florian a šachtě Krystyna."
        ),
        route_style="scattered",
        stops=[
            _stop(
                order=1,
                place_id="osm:way:200001",
                name="Huta Pokój – Ruda Śląska",
                short_title="Huta Pokój",
                lat=50.289,
                lon=18.962,
                why_here="Druhá nejstarší huta v Horním Slezsku (1840) s dochovanými válcovnami.",
                narration=(
                    "Přijíždíme k areálu Huta Pokój — kdysi srdci ocelového "
                    "průmyslu Slezska. Komplex stále obsahuje válcovny z 19. "
                    "století a torzo vysokých pecí, které tvořily horizont "
                    "Rudy Śląské po více než sto let."
                ),
                media_id="wikimedia:Huta_Pokój_w_Rudzie_Śląskiej.jpg",
                wikipedia_summary=(
                    "Huta Pokój je železárna v Rudě Śląské v Horním Slezsku, "
                    "založená v roce 1840. Patří mezi nejstarší dochované "
                    "ocelárny v Polsku; hlavní válcovna je vedena jako "
                    "průmyslová památka. Po útlumu výroby v 80. letech areál "
                    "částečně chátrá, část je veřejně přístupná."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Huta_Pok%C3%B3j",
            ),
            _stop(
                order=2,
                place_id="osm:way:200002",
                name="Huta Florian – Świętochłowice",
                short_title="Huta Florian",
                lat=50.334,
                lon=19.061,
                why_here="Vysoká pec z roku 1827, dnes zarostlá; jedno z nejmalebnějších torz regionu.",
                narration=(
                    "Florian byla první koksová huta v polské části Slezska. "
                    "Dochované cihlové komíny tvoří charakteristickou siluetu, "
                    "kterou znáte z fotografií industriální archeologie."
                ),
                media_id="wikimedia:Huta_Florian.jpg",
                wikipedia_summary=(
                    "Huta Florian byla železárna ve Świętochłowicích, "
                    "založená kolem roku 1827. Provoz byl zastaven v roce "
                    "1992; část areálu je dnes opuštěná, část slouží jako "
                    "lokace pro filmování a workshopy industriálního umění."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Huta_Florian",
            ),
            _stop(
                order=3,
                place_id="osm:node:100003",
                name="Szyb Krystyna – Bytom",
                short_title="Šachta Krystyna",
                lat=50.345,
                lon=18.916,
                why_here="Vodárenská věž černouhelné šachty z roku 1867, dnes solitér v krajině.",
                narration=(
                    "Šachta Krystyna byla otevřena v polovině 19. století "
                    "jako součást těžební společnosti hraběte Henckela. "
                    "Po uzavření v roce 1991 zůstala vodárenská věž jako "
                    "osamocený prvek mezi panelovými sídlišti Bytomu."
                ),
                media_id="wikimedia:Szyb_Krystyna_Bytom.jpg",
                wikipedia_summary=(
                    "Szyb Krystyna byla černouhelná těžební šachta v Bytomu, "
                    "v provozu 1867–1991. Po uzavření zůstala dochována "
                    "vodárenská věž, která je dnes památkově chráněna."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Szyb_Krystyna",
            ),
        ],
    )
)

SAMPLES.append(
    _experience(
        slug="bohemian-paradise-rocks",
        title="Skalní města Českého ráje",
        teaser=(
            "Pětistovková zastávka mezi Hrubou Skálou a Suchými skalami — "
            "pískovcové věže, hrady na hřebeni a vyhlídky nad Jizerou."
        ),
        cover_image=(
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            "Hrub%C3%A1_Sk%C3%A1la_-_panor%C3%A1ma.jpg?width=600"
        ),
        prompt="malebná skalní města a hrady v Českém ráji",
        region="Czech Paradise",
        summary=(
            "Český ráj nabízí jednu z nejhustších koncentrací pískovcových "
            "skalních měst ve střední Evropě. Trasa kombinuje turistické "
            "klasiky (Hrubá Skála, Trosky) s méně známými vyhlídkami."
        ),
        route_style="linear",
        stops=[
            _stop(
                order=1,
                place_id="osm:way:200101",
                name="Hrad Trosky",
                short_title="Hrad Trosky",
                lat=50.515,
                lon=15.232,
                why_here="Symbol celého Českého ráje — zřícenina na dvojvrší vulkanického původu.",
                narration=(
                    "Vstupujeme do Trosek od jihu. Dvě věže — Baba a Panna "
                    "— stojí na pozůstatcích dvou samostatných čedičových "
                    "kuželů. Z dolního ochozu se otevírá pohled na celé "
                    "Maloskalsko a v dobré viditelnosti až na Krkonoše."
                ),
                media_id="wikimedia:Trosky_Castle.jpg",
                wikipedia_summary=(
                    "Trosky jsou zřícenina hradu na čedičových sopouších "
                    "vyvřelin v okrese Semily. Vznikly koncem 14. století; "
                    "dvě věže Baba a Panna patří mezi nejznámější siluety "
                    "české krajiny. Hrad spravuje Národní památkový ústav."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Trosky",
            ),
            _stop(
                order=2,
                place_id="osm:way:200102",
                name="Hrubá Skála – zámek a skalní město",
                short_title="Hrubá Skála",
                lat=50.532,
                lon=15.190,
                why_here="Renesanční zámek nad pískovcovými skalními věžemi, oblíbená horolezecká destinace.",
                narration=(
                    "Hrubá Skála vznikla jako gotický hrad na pískovcovém "
                    "ostrohu, později přestavěný do renesanční podoby. "
                    "Pod zámkem se rozkládá skalní město s 30+ pojmenovanými "
                    "věžemi; horolezci sem jezdí od 50. let."
                ),
                media_id="wikimedia:Hruba_Skala_panorama.jpg",
                wikipedia_summary=(
                    "Hrubá Skála je zámek a stejnojmenné skalní město "
                    "v Českém ráji. Renesanční přestavbu v 16. století "
                    "objednali Smiřičtí ze Smiřic. Areál spadá pod CHKO "
                    "Český ráj a UNESCO geopark."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Hrub%C3%A1_Sk%C3%A1la",
            ),
            _stop(
                order=3,
                place_id="osm:node:100103",
                name="Suché skály",
                short_title="Suché skály",
                lat=50.638,
                lon=15.181,
                why_here="Pískovcový hřeben s 17 věžemi nad údolím Jizery, méně známé než Trosky.",
                narration=(
                    "Suché skály jsou ostrý pískovcový hřeben táhnoucí se "
                    "nad obcí Besedice. Horolezecké tradice tu sahají do "
                    "20. let; nejvyšší věž Kapelník měří 70 metrů. Z hřebene "
                    "vidíte na Ještěd i na Bezděz."
                ),
                media_id="wikimedia:Suche_skaly.jpg",
                wikipedia_summary=(
                    "Suché skály jsou pískovcový hřeben v Maloskalsku, "
                    "součást CHKO Český ráj. Tvoří je 17 souvisle "
                    "vystupujících věží orientovaných od severu k jihu."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Such%C3%A9_sk%C3%A1ly",
            ),
        ],
    )
)

SAMPLES.append(
    _experience(
        slug="moravian-wine-roadtrip",
        title="Vinařský okruh jižní Moravou",
        teaser=(
            "Linearní přejezd od Mikulova přes Pavlovské vrchy do Lednice — "
            "vinice, sklepní uličky a barokní krajinný park."
        ),
        cover_image=(
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            "Lednick%C3%BD_z%C3%A1mek_-_celkov%C3%BD_pohled.jpg?width=600"
        ),
        prompt="vinařský roadtrip na jižní Moravě",
        region="South Moravia",
        summary=(
            "Trasa prochází srdcem moravského vinařství — od kamenných "
            "kostelíků nad Mikulovem přes Pálavu po lednicko-valtický areál, "
            "který UNESCO uvádí jako největší krajinný park Evropy."
        ),
        route_style="linear",
        stops=[
            _stop(
                order=1,
                place_id="osm:way:200201",
                name="Svatý kopeček – Mikulov",
                short_title="Svatý kopeček",
                lat=48.808,
                lon=16.640,
                why_here="Křížová cesta na vápencovém vrchu nad Mikulovem; nejlepší rozhled na Pálavu.",
                narration=(
                    "Vystupujeme po křížové cestě postavené v 17. století. "
                    "Z vrcholové kaple sv. Šebestiána se otevírá pohled na "
                    "Mikulov, mikulovský zámek a celý hřeben Pálavy."
                ),
                media_id="wikimedia:Mikulov_Svaty_kopecek.jpg",
                wikipedia_summary=(
                    "Svatý kopeček je vápencový vrch nad Mikulovem (363 m). "
                    "Křížová cesta s kaplí svatého Šebestiána pochází z let "
                    "1623–1630. Areál spadá pod CHKO Pálava a je národní "
                    "kulturní památkou."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Svat%C3%BD_kope%C4%8Dek_(Mikulov)",
            ),
            _stop(
                order=2,
                place_id="osm:way:200202",
                name="Děvičky – zřícenina hradu",
                short_title="Děvičky",
                lat=48.870,
                lon=16.638,
                why_here="Zřícenina románského hradu na hřebeni Pavlovských vrchů — výhled na obě strany Pálavy.",
                narration=(
                    "Devín, místně Děvičky, byl postaven kolem roku 1222. "
                    "Z jihu vidíte Mikulov a rakouskou hranici, ze severu "
                    "Novomlýnské nádrže a Pálavu. Cesta vede po hřebeni, "
                    "v parném létě bez stínu — vyrazte ráno."
                ),
                media_id="wikimedia:Devicky.jpg",
                wikipedia_summary=(
                    "Děvičky (též Maidenburg) jsou zřícenina hradu na "
                    "vrcholu Děvín v Pavlovských vrších. Hrad pochází z "
                    "první třetiny 13. století; zničen byl Švédy roku 1645. "
                    "Areál je součástí CHKO Pálava."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/D%C4%9Bvi%C4%8Dky",
            ),
            _stop(
                order=3,
                place_id="osm:way:200203",
                name="Lednicko-valtický areál",
                short_title="Lednice",
                lat=48.802,
                lon=16.805,
                why_here="Největší krajinný park Evropy — UNESCO; novogotický zámek + Minaret + Janův hrad.",
                narration=(
                    "Lednicko-valtický areál je 285 km² komponovaná "
                    "krajina vytvořená Lichtenštejny v 19. století. "
                    "Z lednického zámku můžete jít pěšky 2 km k Minaretu "
                    "(60 m vysoká rozhledna v maurském stylu) nebo pokračovat "
                    "k Janovu hradu — fingované zřícenině z roku 1810."
                ),
                media_id="wikimedia:Lednicky_zamek.jpg",
                wikipedia_summary=(
                    "Lednicko-valtický areál je komponovaná krajina o "
                    "rozloze 285 km² na jižní Moravě. Vytvořili ji "
                    "Lichtenštejnové v 17.–19. století. Od roku 1996 je "
                    "zapsán na seznam světového dědictví UNESCO."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Lednicko-valtick%C3%BD_are%C3%A1l",
            ),
        ],
    )
)

SAMPLES.append(
    _experience(
        slug="tatra-mountain-passes",
        title="Drsná horská sedla Vysokých Tater",
        teaser=(
            "Tři vyhlídková sedla nad 1900 m — od Kriváně přes Bystré sedlo "
            "po Sedielko. Nutná dobrá kondice a pevné boty."
        ),
        cover_image=(
            "https://commons.wikimedia.org/wiki/Special:FilePath/"
            "Krivan_z_Hladkeho_titu.jpg?width=600"
        ),
        prompt="drsná horská sedla a štíty Vysokých Tater",
        region="High Tatras",
        summary=(
            "Tři ze symbolicky nejtvrdších sedel hlavního hřebene Vysokých "
            "Tater. Trasa je rozložena přes 2–3 dny s noclehem v útulně; "
            "vyžaduje letní podmínky a slušnou výškovou aklimatizaci."
        ),
        route_style="scattered",
        stops=[
            _stop(
                order=1,
                place_id="osm:node:100301",
                name="Kriváň (2495 m)",
                short_title="Kriváň",
                lat=49.155,
                lon=20.000,
                why_here="Národní symbol Slovenska; klasický celodenní výstup po značené trase.",
                narration=(
                    "Kriváň je 2495 m vysoký štít na západním okraji "
                    "Vysokých Tater. Klasický výstup začíná na Tří "
                    "studničkách a trvá 8–10 hodin tam i zpět. Z vrcholu "
                    "vidíte hlavní hřeben Tater i Nízké Tatry."
                ),
                media_id="wikimedia:Krivan_z_Hladkeho_titu.jpg",
                wikipedia_summary=(
                    "Kriváň je 2495 m vysoký štít v západní části Vysokých "
                    "Tater. Pro Slováky je národním symbolem; jeho silueta "
                    "je vyobrazena na 1- a 2-eurových mincích vyražených na "
                    "Slovensku."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Kriv%C3%A1%C5%88",
            ),
            _stop(
                order=2,
                place_id="osm:node:100302",
                name="Bystré sedlo (2314 m)",
                short_title="Bystré sedlo",
                lat=49.183,
                lon=20.156,
                why_here="Jedno z nejvyšších značených sedel Vysokých Tater, mezi Bystrou a Furkotskou dolinou.",
                narration=(
                    "Sedlo leží mezi Furkotským a Mlynickým štítem ve výšce "
                    "2314 m. Klasický přechod vede z Furkotské doliny "
                    "(přístup z Pleso pod Soliskom) do Mlynické doliny — "
                    "středně náročná, ale exponovaná trasa s řetězy."
                ),
                media_id="wikimedia:Bystre_sedlo.jpg",
                wikipedia_summary=(
                    "Bystré sedlo je horské sedlo ve Vysokých Tatrách "
                    "(2314 m) mezi Furkotským a Mlynickým štítem. Patří "
                    "mezi nejvyšší značené přechody hlavního hřebene; "
                    "trasa je sezonně uzavřena pro lavinové riziko."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Bystr%C3%A9_sedlo",
            ),
            _stop(
                order=3,
                place_id="osm:node:100303",
                name="Sedielko (2376 m)",
                short_title="Sedielko",
                lat=49.181,
                lon=20.221,
                why_here="Nejvyšší značené sedlo Vysokých Tater; přechod z Malé Studené do Velké Studené doliny.",
                narration=(
                    "Sedielko ve výšce 2376 m je nejvyšším značeným sedlem "
                    "celých Vysokých Tater. Cesta z Téryho chaty stoupá "
                    "drsnou suťovou stezkou; pohled z vrcholu zabírá "
                    "Lomnický štít, Gerlach i Belianské Tatry."
                ),
                media_id="wikimedia:Sedielko.jpg",
                wikipedia_summary=(
                    "Sedielko je horské sedlo ve Vysokých Tatrách (2376 m), "
                    "nejvyšší značený přechod hlavního hřebene. Spojuje "
                    "Malou a Velkou Studenou dolinu; trasa je vedena přes "
                    "feratové úseky a v zimě je uzavřena."
                ),
                wikipedia_url="https://cs.wikipedia.org/wiki/Sedielko",
            ),
        ],
    )
)


def main() -> None:
    written: list[str] = []
    for sample in SAMPLES:
        slug = sample["slug"]
        out = OUT_DIR / f"{slug}.json"
        with out.open("w", encoding="utf-8") as f:
            json.dump(sample, f, ensure_ascii=False, indent=2)
        written.append(slug)
    print(f"Wrote {len(written)} samples to {OUT_DIR}:")
    for s in written:
        print(f"  - {s}.json")


if __name__ == "__main__":
    main()
