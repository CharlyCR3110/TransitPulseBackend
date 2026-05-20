"""Build the canonical stop dictionary for the SJ↔Heredia corridor.

Each unique stop in the corridor (after dedup of spelling variants) gets a
``CanonicalStop`` row with:
    - id              — slug ≤ 32 chars (DB column is VARCHAR(32))
    - label_es / label_en
    - addr_es / addr_en
    - tier            — anchor | landmark | mid | corner
    - raw_names       — list of every Moovit name that maps here
    - geocode_query   — for the Nominatim batch (None for tier=corner)

How IDs are decided:

1. ``CANONICAL_IDS`` below: hand-curated raw_name → id mapping for stops we
   already have an ID for in the existing seed (e.g. ``her_walmart``), or that
   need a non-obvious slug (e.g. ``her_estadio`` for "Estadio Eladio Rosabal
   Cordero").
2. ``DEDUP_ALIASES``: extra raw names that should fold to the same canonical
   stop as another name (e.g. "Plaza Bratsi" → "Plaza Bratzi").
3. For anything not in those tables, an auto-slug is derived from the cleaned
   name + canton prefix.

The point of having (1)+(2)+(3) is reviewability: the user can scan
``corridor_stops_review.json`` and the only entries needing attention are
those with ``review_needed = true`` (long auto-slugs, untiered, etc.).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from scripts.corridor.parse import Direction, load_route_directions, load_verified_coords

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "TransitPulseBackend/scripts/corridor/out"

MAX_ID_LEN = 32


# ----------------------------------------------------------------------------
# (1) Canonical IDs for stops with established or carefully-chosen slugs.
#     Keys are RAW Moovit stop names (exact strings from heredia-routes.md).
#     Values are the canonical ID (≤ 32 chars). When in doubt, prefer existing
#     IDs from app/seed/stops.json so we don't duplicate rows.
# ----------------------------------------------------------------------------
CANONICAL_IDS: dict[str, str] = {
    # --- Terminals ---
    "Terminal Heredia, Contiguo A Súper Fácil": "her_term_400",
    "Terminal Heredia, Frente A Mercado Central Heredia": "her_term_mc",
    "Terminal Heredia, Frente A Escuela Braulio Morales": "her_term_braulio",
    "Terminal Heredia, Predio Transportes Unidos La 400 S.A.": "her_term_la400_pirro",
    "Terminal Heredia, Frente A Predio Transportes Unidos La 400 S.A.": "her_term_la400_pirro",
    "Terminal Rápidos Heredianos, San José": "sj_term_rh",
    "Terminal San José": "sj_term_400u",
    "Terminal La Aurora": "her_term_aurora",
    "Terminal Cenada, Heredia": "her_cenada",

    "Terminal Heredia, Costado Norte Mercado Heredia": "her_term_mc",
    "Terminal Cenada, Frente A Carpesheredia": "her_cenada",

    # --- Big anchors (existing IDs in seed) ---
    "Walmart Ulloa, Heredia": "her_walmart",
    "Pricesmart Heredia": "her_pricesmart",
    "Hotel Irazú, Autopista General Cañas San José": "sj_irazu",
    "Hotel Crown Plaza Corobicí, Autopista General Cañas San José": "sj_corobici",
    "Universidad Nacional De Costa Rica, Heredia": "her_una",
    "Frente A Estadio Eladio Rosabal Cordero, Heredia": "her_estadio",
    "Cercanías A Estadio Eladio Rosabal Cordero, Heredia": "her_estadio_pre",
    "Costado Oeste Terminal 7-10, Paso De La Vaca San José": "sj_term_cocacola",

    # --- Bridges (pre/post are physically distinct curbs) ---
    # `pte_virilla` already exists in seed at the Heredia-side curb; reuse for
    # "Posterior A Puente Río Virilla" (SJ-bound bus has just crossed = on the
    # SJ side, post-bridge from SJ-bound perspective). The pre-bridge curb
    # (Heredia-bound) gets a new id.
    "Previo A Puente Río Virilla, Vuelta Del Virilla San José": "pte_virilla_pre",
    "Posterior A Puente Río Virilla, Vuelta Del Virilla San José": "pte_virilla",
    "Posterior A Puente Río Bermudez, Barreal Heredia": "pte_bermudez_post",
    "Posterior A Puente Río Bermúdez, Barreal Heredia": "pte_bermudez_post",
    "Previo A Puente Río Bermúdez, Barreal Heredia": "pte_bermudez_pre",

    # --- Universities ---
    "Universidad Politécnica Internacional, Heredia": "her_upi",
    "Universidad Hispanoamericana, Pirro Heredia": "her_uhispano",
    "Frente A Universidad Fidélitas Campus Sede Santa Cecilia, Heredia": "her_fidelitas",
    "Universidad Fidélitas Sede Santa Cecilia, Heredia": "her_fidelitas",
    "Frente A Campus Presbítero Benjamín Núñez Universidad Nacional, Lagunilla Heredia": "her_una_lagunilla",
    "Campus Presbítero Benjamín Núñez Universidad Nacional, Lagunilla Heredia": "her_una_lagunilla",

    # --- Hospitals/clinics ---
    "Clínica De Heredia, Fátima Heredia": "her_clinica_heredia",
    "Antiguo Hospital San Vicente De Paul": "her_hospital_svp",
    "Contiguo A Área De Salud Clínica Dr. Francisco Bolaños, Fátima De Heredia": "her_clinica_bolanos",
    "Frente A EBAIS De Santo Domingo": "sd_ebais",
    "Frente A Ebais La Aurora, Heredia": "her_ebais_aurora",

    # --- Public buildings ---
    "Oficinas Centrales ICT, La Uruca San José": "sj_ict",
    "Cercanía A Migración, La Uruca San José": "sj_migracion",
    "Cercanía Migración, La Uruca San José": "sj_migracion",
    "Frente A Plantel Del MOPT De Santo Domingo": "sd_mopt",
    "Plantel Del MOPT De Santo Domingo": "sd_mopt",
    "Cercanías A Agencia INS San Juan, Tibás": "tib_ins",
    "Agencia BAC Credomatic San Juan, Tibás": "tib_bac",
    "Contiguo A Estación De Bomberos Santo Domingo": "sd_bomberos",

    # --- Major retail / fmcg landmarks ---
    "Más X Menos Mántica, Autopista General Cañas San José": "sj_mxm_mantica",
    "Más X Menos De San Pablo": "sp_mxm",
    "Frente A Palí De Santo Domingo": "sd_pali",
    "Frente A MC Donald's De Santo Domingo": "sd_mcd",
    "Contiguo A MC Donald's De Santo Domingo": "sd_mcd",
    "Contiguo A MC Donald's La Valencia, Heredia": "her_mcd_valencia",
    "Contiguo A Burguer King Plaza Santo Domingo": "sd_bk_plaza",
    "Pops Santa Mónica, Tibás": "tib_pops",
    "Paseo De Las Flores, Heredia": "her_paseo_flores",
    "Pequeño Mundo, Heredia": "her_pequeno_mundo",
    "Frente A Walmart Los Lagos": "her_walmart_los_lagos",
    "Diagonal A Hotel Tryp Sabana, Mántica San José": "sj_tryp_sabana",
    "Contiguo A Hotel D Cristina, Heredia": "her_hotel_cristina",
    "Fábrica Nacional De Chocolates, Heredia": "her_fab_chocolates",
    "Frente A Florida Bebidas, Barreal Heredia": "her_florida_bebidas",
    "Contiguo A Entrada Florida Bebidas, Barreal Heredia": "her_florida_bebidas",
    "Zona Franca Metropolitana, Barreal Heredia": "her_zf_metropolitana",
    "FTZ Coca Cola La Uruca, San José": "sj_ftz_cocacola",
    "Agencia Purdy Motor, Zona Industrial La Uruca San José": "sj_purdy_motor",
    "Frente A Agencia Purdy Motor, Zona Industrial La Uruca San José": "sj_purdy_motor",
    "Agencia Renault La Uruca, San José": "sj_renault",
    "Frente A Plaza Bratzi, Heredia": "her_plaza_bratzi",
    "Plaza Bratsi, Heredia": "her_plaza_bratzi",  # spelling variant
    "Frente A Plaza Santo Domingo": "sd_plaza",

    # --- Cemeteries ---
    "Cementerio Municipal De San Pablo": "sp_cementerio",
    "Cementerio Barreal, Heredia": "her_cementerio_barreal",
    "Frente A Cementerio Extranjero, San José": "sj_cementerio_extranjero",

    # --- Schools / churches ---
    "Costado Norte Escuela Juan Rafael Mora, Pitahaya San José": "sj_esc_jrm",
    "Frente A Escuela Villalobos, Lagunilla Heredia": "her_esc_villalobos",
    "Frente A Escuela La Aurora": "her_esc_aurora",
    "Frente A Liceo Urb. Los Lagos, Heredia": "her_liceo_los_lagos",
    "Costado Sur Gimnasio Liceo De Heredia": "her_liceo_gym",
    "Iglesia Casa De Oración San Pablo": "sp_iglesia_oracion",
    "Costado Posterior Iglesia Católica De El Rosario, Santo Domingo": "sd_iglesia_rosario",
    "Parroquia Corpus Christi La Aurora, Heredia": "her_parroquia_aurora",
    "Parroquia Patriarca San José, Barreal Heredia": "her_parroquia_barreal",
    "Iglesia Cristiana Monte Hareb, Urb. La Victoria Heredia": "her_iglesia_hareb",
    "Frente A Iglesia Cristiana Monte Hareb, Urb. La Victoria Heredia": "her_iglesia_hareb",
    "Frente A Iglesia Tierra De Milagros, Cinco Esquinas De Tibás": "sj_tibas_cinco",

    # --- Plazas / parks ---
    "Diagonal A Plaza De Deportes La Puebla, Heredia": "her_plaza_puebla",
    "Frente A Plaza De Deportes La Puebla, Heredia": "her_plaza_puebla",
    "Plaza De Deportes La Uruca, San José": "sj_plaza_uruca",
    "Parque De La Aurora, Heredia": "her_parque_aurora",
    "Frente A Parque Aries, La Aurora Heredia": "her_parque_aries",
    "Parque Santa Cecilia, Heredia": "her_parque_sta_cecilia",
    "Costado Norte Parque La Democracia, San Juan De Tibás": "tib_parque_democracia",

    # --- Stops named for ARH plantel (separate from terminal MRH) ---
    "Plantel Autobuses Rápidos Heredianos, Pirro Heredia": "her_plantel_mrh",
    "Plantel Caribeños, Cinco Esquinas De Tibás": "tib_plantel_caribenos",

    # --- Auto/repair-shop names that are local landmarks ---
    "Repuestos Gigante La Valencia, Heredia": "her_repuestos_gigante",
    "Frente A Autos Xiri / Antigua Peugeot, La Valencia Heredia": "her_autos_xiri",
    "Autos Usados Xiri, San Juan De Tibás": "tib_autos_xiri",
    "Contiguo A Autos El Poblado, Santo Domingo": "sd_autos_poblado",
    "Diagonal Autos El Poblado, Santo Domingo": "sd_autos_poblado",
    "Contiguo A Autos Santo Domingo": "sd_autos_sd",
    "Contiguo A Kia Motors": "her_kia",
    "Autopits Heredia Pirro, Heredia": "her_autopits_pirro",

    # --- Tibás / Tournón ---
    "Intersección Barrio Tournon, San José": "sj_tournon_int",
    "Multiservicios Edos, Tournón San José": "sj_tournon_edos",
    "Frente A Multiservicios Edus, Tournón San José": "sj_tournon_edos",   # typo variant
    "Contiguo A Servicentro Tournón, San José": "sj_tournon_servicentro",
    # Existing seed has `sj_tibas_cinco` at Cinco Esquinas — reuse for both
    # named stops there to inherit the coord.
    "Frente A Guitarras Arristedes Guzmán, Cinco Esquinas De Tibás": "sj_tibas_cinco",
    "Frente A Servicentro Coopetaxi, San Juan De Tibás": "tib_coopetaxi",
    "Frente A Pizza Hut San Juan, Tibás": "tib_pizzahut",

    # --- 400u-only landmarks ---
    "Polideportivo Santa Cecilia, Heredia": "her_polideportivo",
    "Frente A Polideportivo Santa Cecilia, Heredia": "her_polideportivo",
    "Marisquería Mar Y Fuego, Santa Cecilia Heredia": "her_mar_y_fuego",
    "Marisqueria Mar Y Fuego, Santa Cecilia Heredia": "her_mar_y_fuego",
    "Frente A Pizzería Santa Cecilia, Heredia": "her_pizza_sta_cecilia",
    "Mas Pollo Santa Cecilia, Heredia": "her_mas_pollo",
    "Tanque Agua La Aurora, Heredia": "her_tanque_aurora",
    "Frente A Tanque Agua La Aurora, Heredia": "her_tanque_aurora",
    "Curva Entrada La Aurora, Heredia": "her_curva_aurora",
    "Frente A Centro Comercial Lagunilla, Heredia": "her_cc_lagunilla",
    "Plaza Comercial Allegro, Lagunilla Heredia": "her_plaza_allegro",
    "Frente A Super Taim, Lagunilla Heredia": "her_super_taim",
    "Super Taim, Lagunilla Heredia": "her_super_taim",
    "Frente A Ultrapark Lagunilla, Heredia": "her_ultrapark",
    "Ultrapark Lagunilla, Heredia": "her_ultrapark",
    "Frente A Ampm, Barreal Heredia": "her_ampm_barreal",
    "Servicentro Uno Barreal, Heredia": "her_servicentro_barreal",
    "Frente A Servicentro Uno Barreal, Heredia": "her_servicentro_barreal",
    "Frente A Servicentro Casaque, Heredia": "her_servicentro_casaque",

    # --- 402-only stops (Heredia - Cenada - Lagunilla) ---
    "Frente A Pizza Hut, Heredia": "her_pizza_hut",
    "Contiguo A Plaza De Deportes Barreal, Heredia": "her_plaza_dep_barreal",
    "Contiguo A Rest. Tasty Pizza, Heredia": "her_tasty_pizza",
    "Frente Al Megasúper, Heredia": "her_megasuper",

    # --- 402 aliases (same physical stop, different Moovit name) ---
    "Contiguo A Entrada Resid. Real Santamaría, Lagunilla Heredia": "her_real_santamaria",
    "Frente A Laboratorios Griffith, Lagunilla Heredia": "her_lab_grith",
    "Laboratorios Griffith, Lagunilla Heredia": "her_lab_grith",
    "Frente A Batidos Naturales Cosechas, Barreal Heredia": "her_cosechas_barreal",
    "Walmart Los Lagos, Heredia": "her_walmart_los_lagos",

    # --- 400sd-only Santo Domingo / San Pablo ---
    "Panadería Y Repostería Chantilly, San Pablo": "sp_pan_chantilly",
    "Lavacar Olas, San Pablo": "sp_lavacar_olas",
    "Frente A Taller Sys, San Pablo": "sp_taller_sys",
    "Contiguo A Taller Sys, San Pablo": "sp_taller_sys",
    "Contiguo A Entrada Colegio Europeo, San Pablo": "sp_colegio_europeo",
    "Contiguo A Entrada Cond. Eco Heredia Urbano, La Puebla De Heredia": "her_eco_urbano",
    "Frente A Sognos Café, Santo Domingo": "sd_sognos",
    "Entrada A Barrio Santa Rosa, Santo Domingo": "sd_barrio_sta_rosa",
    "Centro De Carnes Santa Rosa, Santo Domingo": "sd_carnes_sta_rosa",
    "Frente A Pizerría Napoli, Santo Domingo": "sd_pizza_napoli",
    "Minisuper El Buen Precio, Santo Domingo": "sd_minisuper_bp",
    "Contiguo A Minibodegas, Santo Domingo": "sd_minibodegas",
    "Frente A Centro Cultura Lapa Verde, Santo Domingo": "sd_lapa_verde",

    # --- Other ---
    "Conapdis, La Valencia Heredia": "her_conapdis",
    "Contiguo A Palacio De La Cerámica, Pirro Heredia": "her_palacio_ceramica",
    "Frente A Panadería Y Repostería Leandro, Fátima De Heredia": "her_pan_leandro",
    "Super Miraflores, Pirro Heredia": "her_super_miraflores",
    "Contiguo A Pricesmart": "her_pricesmart_acera",  # opposite curb of her_pricesmart
    "Antigua Arrocera El Sabanero, La Valencia De Heredia": "her_arrocera_sabanero",
    "Antigua Arrocera El Sabanero, La Valencia Heredia": "her_arrocera_sabanero",
    "Comercial Heredia 2000, Heredia": "her_comercial_2000",
    "Frente A Envases Comeca, La Uruca San José": "sj_comeca",
    "Antigua Lacsa, La Uruca San José": "sj_lacsa",
    "Tienda Sagot, La Uruca San José": "sj_sagot",
    "Monumento Agua, Autopista General Cañas San José": "sj_monumento_agua",
    "Contiguo A Tienda Yamuni, San Francisco San José": "sj_yamuni",
    "Contiguo A Rest. Phad Thai, Pitahaya San José": "sj_phadthai",
    "Funeraria Del Magisterio Nacional, Pitahaya San José": "sj_funeraria_mag",
    "Grupo Sonmerus, San Juan De Tibás": "tib_sonmerus",
    "Parqueo Publico Sabucedo, San Juan De Tibás": "tib_sabucedo",
    "Contiguo A Rest. Gran Oriente, San Juan Tibás": "tib_gran_oriente",
    "Contiguo A Super La Valvanera, San Juan De Tibás": "tib_valvanera",
    "Frente A Super La Valvanera, San Juan De Tibás": "tib_valvanera",
    "Frente A Mueblería La Kasa, San Juan De Tibás": "tib_mueb_la_kasa",
    "Contiguo A Autoservicio Morocco, San Juan De Tibás": "tib_morocco",

    # --- 400u stops south of the Virilla bridge (SJ side) ---
    "Centro De Convivencia Ejército De Salvación, Bajos De La Unión San José": "sj_ejercito_salvacion",
    "Antigua Botica Solera, Barrio México San José": "sj_botica_solera",
    "Abastecedor El Guanacasteco, Iglesias Flores San José": "sj_guanacasteco",
    "Contiguo A Agencia Ford, Bajo Torres San José": "sj_ford",
    "Motores Británicos, Piemonte San José": "sj_mot_britanicos",
    "Faco La Uruca, Piemonte San José": "sj_faco_uruca",
    "Auto Star La Uruca, San José": "sj_autostar",
    "Great Wall La Uruca, San José": "sj_greatwall",
    "Contiguo A Matra La Uruca, San José": "sj_matra",
    "Corporación Font, Zona Industrial La Uruca San José": "sj_font",
    "Agencia CN Plantel Virrilla, Zona Industrial La Uruca San José": "sj_cn_virilla",
    "Frente A Agencia Purdy Motor, Zona Industrial La Uruca San José": "sj_purdy_motor",
    "Agencia Autos Geely, La Uruca San José": "sj_geely",
    "Agencia De Motocicletas Suzuki, La Uruca San José": "sj_suzuki",
    "Credi Motors, Iglesias Flores San José": "sj_credi_motors",

    # --- 400u stops in Barreal / Lagunilla ---
    "Peluditos Pet Shop, La Aurora Heredia": "her_peluditos",
    "Agencia De Publicidad Publiex, La Aurora Heredia": "her_publiex",
    "Fabrica Nacional De Bolsas, Barreal Heredia": "her_fab_bolsas",
    "Contiguo A Soda Ponche Real, Barreal Heredia": "her_soda_ponche",
    "Cercanías Cruce La Aurora, Barreal Heredia": "her_cruce_aurora",
    "Centro De Negocios Barreal, Heredia": "her_cn_barreal",
    "Frente A Multicomercial Baden, Barreal Heredia": "her_multicomercial_baden",
    "Batidos Naturales Cosechas Barreal, Heredia": "her_cosechas_barreal",
    "Cruce Con Calle Azofeifa, Lagunilla Heredia": "her_calle_azofeifa",
    "Interlogic, Lagunilla Heredia": "her_interlogic",
    "Contiguo A Entrada Jardines Del Recuerdo, La Valencia Heredia": "her_jard_recuerdo",
    "Contiguo A Entrada Jardines Del Recuerdo, La Valencia De Heredia": "her_jard_recuerdo",
    "Entrada Res. Real Santamaría, Lagunilla Heredia": "her_real_santamaria",
    "Contiguo A Entrada Res. Real Santamaria Oeste, Barreal Heredia": "her_real_santamaria_o",
    "Contiguo A Entrada Resid. Real Santamaria Oeste, Barreal Heredia": "her_real_santamaria_o",
    "Frente A Laboratorios Grith, Lagunilla Heredia": "her_lab_grith",
    "Contiguo A Entrada Cond. Vía Heredia, San Pablo": "sp_cond_via_heredia",
    "Frente A Rest. La Perla De Asia, San Pablo": "sp_perla_asia",
    "Contiguo A Entrada Miraflores, San Pablo": "sp_miraflores",
    "Frente A Rest. La Esquina Del Sabor, San Pablo": "sp_esquina_sabor",
    "Contiguo A Entrada Cond. Vistas De San Pablo, San Pablo": "sp_vistas_sp",
    "Restaurante Estrella China, La Aurora Heredia": "her_estrella_china",
    "La Aurora Sur - Avenida Guanacaste, La Aurora Heredia": "her_aurora_sur",
    "Frente A Super San Francisco, Urb. La Victoria Heredia": "her_super_sanfran",
    "Frente A Super Taim, Lagunilla Heredia": "her_super_taim",
    "Entrada Sur Cond. Hacienda San Agustín, Santa Cecilia Heredia": "her_san_agustin_sur",
    "Frente A Entrada Sur Cond. San Agustín, Santa Cecilia Heredia": "her_san_agustin_sur",
    "Shots Lico Market, Santa Cecilia Heredia": "her_shots_lico",
    "Contiguo A Supermercado San Francisco, Urb. La Victoria Heredia": "her_super_sanfran",
    "Contiguo A Entrada Urb. Los Lagos, Heredia": "her_los_lagos_entr",
    "Frente A Outlet Center, Barreal Heredia": "her_outlet_center",
    "Frente A Congelados Del Monte, Barreal Heredia": "her_congelados_monte",
    "Contiguo A Entrada Cond. Eco Heredia Urbano, La Puebla De Heredia": "her_eco_urbano",
}


# ----------------------------------------------------------------------------
# (3) Auto-slug helpers.
# ----------------------------------------------------------------------------
_AREA_PREFIX_MAP: list[tuple[re.Pattern[str], str]] = [
    # Order matters: most specific first.
    (re.compile(r"Santo Domingo", re.I), "sd_"),
    (re.compile(r"San Pablo", re.I), "sp_"),
    (re.compile(r"Tibás|Tibas|Tournón|Tournon", re.I), "tib_"),
    (re.compile(r"Heredia|Pirro|Mercedes|Barreal|Lagunilla|Fátima|Fatima|Ulloa|San Joaquín|San Rafael|Puebla|Aurora|Cecilia|Victoria", re.I), "her_"),
    (re.compile(r"San José|San Jose|Uruca|Sabana|Pitahaya|Mántica|Mantica|Iglesias Flores|Piemonte|Bajos De La Unión|Barrio México", re.I), "sj_"),
]

_STRIP_LEAD_PREFIXES = re.compile(
    r"^(?:"
    r"frente a|contiguo a|diagonal a|costado norte|costado sur|costado este|costado oeste|"
    r"cercanías a|cercanía a|cercanías|cercanía|previo a|posterior a|antiguo|antigua|"
    r"cruce con|cruce|entrada a|intersección|interseccion"
    r")\s+",
    re.I,
)


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _area_prefix(name: str) -> str:
    for pat, prefix in _AREA_PREFIX_MAP:
        if pat.search(name):
            return prefix
    return "x_"  # fall-through; flagged for review


def _auto_slug(raw: str) -> str:
    prefix = _area_prefix(raw)
    head = raw.split(",", 1)[0]
    head = _STRIP_LEAD_PREFIXES.sub("", head)
    head = _strip_accents(head).lower()
    head = re.sub(r"[^a-z0-9]+", "_", head).strip("_")
    parts = head.split("_")[:3]
    body = "_".join(parts) or "stop"
    candidate = f"{prefix}{body}"
    return candidate[:MAX_ID_LEN]


# ----------------------------------------------------------------------------
# Tier classification.
# ----------------------------------------------------------------------------
_ANCHOR_PATTERNS = [
    "Terminal", "Hospital", "Clínica De Heredia",
]
_LANDMARK_PATTERNS = [
    "Walmart", "Pricesmart", "PriceSmart", "Universidad", "Estadio",
    "Hotel Irazú", "Hotel Crown", "Plaza Santo Domingo", "Paseo De Las Flores",
    "Pequeño Mundo", "Cenada", "Polideportivo", "Cementerio", "MOPT",
    "EBAIS", "ICT", "Ultrapark", "FTZ Coca Cola", "Zona Franca",
    "Plantel Autobuses Rápidos", "Plaza Bratzi", "Plaza Bratsi",
    "Mc Donald", "MC Donald", "Burguer King", "Pops", "Más X Menos",
    "Palí", "Pali",
]


def _tier_for(raw: str) -> str:
    for p in _ANCHOR_PATTERNS:
        if p.lower() in raw.lower():
            return "anchor"
    for p in _LANDMARK_PATTERNS:
        if p.lower() in raw.lower():
            return "landmark"
    # Heuristic mid: contains a proper-noun business chain we didn't enumerate
    if re.search(r"\b(Súper|Super|Pizzería|Pizzeria|Servicentro|Farmacia|Restaurante|Banco|BAC|Coopetaxi)\b", raw, re.I):
        return "mid"
    return "corner"


def _geocode_query(raw: str, canonical_id: str) -> str | None:
    """Build a Nominatim query string. Returns None for tier=corner."""
    head = raw.split(",", 1)[0]
    head = _STRIP_LEAD_PREFIXES.sub("", head).strip()
    # Add city hint when raw includes it.
    tail = raw.split(",", 1)[1].strip() if "," in raw else ""
    if "Heredia" in tail or canonical_id.startswith("her_"):
        loc = "Heredia, Costa Rica"
    elif canonical_id.startswith(("sd_", "sp_")):
        loc = "Santo Domingo, Heredia, Costa Rica" if canonical_id.startswith("sd_") else "San Pablo, Heredia, Costa Rica"
    elif canonical_id.startswith("tib_"):
        loc = "Tibás, San José, Costa Rica"
    else:
        loc = "San José, Costa Rica"
    return f"{head}, {loc}"


# ----------------------------------------------------------------------------
# Build.
# ----------------------------------------------------------------------------
@dataclass
class CanonicalStop:
    id: str
    label_es: str
    label_en: str
    addr_es: str
    addr_en: str
    tier: str
    raw_names: list[str] = field(default_factory=list)
    geocode_query: str | None = None
    id_source: str = "canonical"   # "canonical" | "auto"
    review_needed: bool = False
    review_reasons: list[str] = field(default_factory=list)


def _english_label(raw_head: str) -> str:
    # Minimal: keep proper nouns, translate a few common Spanish framings.
    s = raw_head
    s = re.sub(r"^Frente A ", "In front of ", s, flags=re.I)
    s = re.sub(r"^Contiguo A ", "Next to ", s, flags=re.I)
    s = re.sub(r"^Diagonal A ", "Diagonal to ", s, flags=re.I)
    s = re.sub(r"^Costado Norte ", "North side of ", s, flags=re.I)
    s = re.sub(r"^Costado Sur ", "South side of ", s, flags=re.I)
    s = re.sub(r"^Costado Este ", "East side of ", s, flags=re.I)
    s = re.sub(r"^Costado Oeste ", "West side of ", s, flags=re.I)
    s = re.sub(r"^Cercanías A ", "Near ", s, flags=re.I)
    s = re.sub(r"^Cercanía A ", "Near ", s, flags=re.I)
    s = re.sub(r"^Cercanías ", "Near ", s, flags=re.I)
    s = re.sub(r"^Previo A ", "Just before ", s, flags=re.I)
    s = re.sub(r"^Posterior A ", "Just after ", s, flags=re.I)
    s = re.sub(r"^Cruce Con ", "Crossing with ", s, flags=re.I)
    s = re.sub(r"^Entrada A ", "Entrance to ", s, flags=re.I)
    return s


def build_canonical_stops(directions: Iterable[Direction]) -> dict[str, CanonicalStop]:
    by_id: dict[str, CanonicalStop] = {}
    seen_raw_to_id: dict[str, str] = {}

    for d in directions:
        for raw in d.stops:
            if raw in seen_raw_to_id:
                continue
            seen_raw_to_id[raw] = ""  # placeholder

            id_, id_source = (CANONICAL_IDS[raw], "canonical") if raw in CANONICAL_IDS else (_auto_slug(raw), "auto")

            review = []
            if len(id_) > MAX_ID_LEN:
                review.append(f"id length {len(id_)} > {MAX_ID_LEN}")
                id_ = id_[:MAX_ID_LEN]
            if id_.startswith("x_"):
                review.append("could not infer canton prefix")
            if id_source == "auto":
                review.append("auto-generated id; consider promoting to CANONICAL_IDS")

            if id_ in by_id:
                by_id[id_].raw_names.append(raw)
            else:
                head = raw.split(",", 1)[0].strip()
                tail = raw.split(",", 1)[1].strip() if "," in raw else ""
                tier = _tier_for(raw)
                by_id[id_] = CanonicalStop(
                    id=id_,
                    label_es=head,
                    label_en=_english_label(head),
                    addr_es=tail,
                    addr_en=tail,
                    tier=tier,
                    raw_names=[raw],
                    geocode_query=_geocode_query(raw, id_) if tier != "corner" else None,
                    id_source=id_source,
                    review_needed=bool(review),
                    review_reasons=review,
                )
            seen_raw_to_id[raw] = id_

    return by_id


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    directions = load_route_directions()
    coords = load_verified_coords()

    canonical = build_canonical_stops(directions)

    # Attach lat/lng from verified coords where the coord-file id matches by name.
    coord_by_name = {c.name.lower(): c for c in coords}
    coord_by_id = {c.id: c for c in coords}
    for cs in canonical.values():
        for raw in cs.raw_names:
            hit = coord_by_name.get(raw.lower())
            if hit:
                cs.geocode_query = None  # no need; we have it
                cs.raw_names = cs.raw_names  # noop, just signal
                break

    # Stats.
    by_tier: dict[str, int] = {}
    review_count = 0
    for cs in canonical.values():
        by_tier[cs.tier] = by_tier.get(cs.tier, 0) + 1
        if cs.review_needed:
            review_count += 1

    total_instances = sum(len(d.stops) for d in directions)

    payload = {
        "summary": {
            "stop_instances": total_instances,
            "unique_canonical_stops": len(canonical),
            "by_tier": by_tier,
            "review_needed": review_count,
            "verified_coord_entries": len(coords),
        },
        "directions": [
            {
                "route_id": d.route_id,
                "direction_id": d.direction_id,
                "from": d.from_,
                "to": d.to_,
                "duration_min": d.duration_min,
                "stop_count": len(d.stops),
                "stop_ids": [
                    CANONICAL_IDS[s] if s in CANONICAL_IDS else _auto_slug(s)
                    for s in d.stops
                ],
            }
            for d in directions
        ],
        "stops": [asdict(cs) for cs in sorted(canonical.values(), key=lambda x: x.id)],
        "verified_coords": [asdict(c) for c in coords],
    }
    out_path = OUT_DIR / "corridor_stops_review.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {out_path.relative_to(REPO_ROOT)}")
    print(f"  stop instances:  {total_instances}")
    print(f"  unique stops:    {len(canonical)}")
    print(f"  by tier:         {by_tier}")
    print(f"  review needed:   {review_count}")


if __name__ == "__main__":
    main()
