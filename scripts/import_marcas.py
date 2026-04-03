"""
scripts/import_marcas.py
Importa la lista de marcas de ROADRUNNINGReview en bloque.
Ejecutar con: python scripts/import_marcas.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from models.database import create_db_engine, init_db, Medio, Marca, EstadoEntidadEnum
from core.settings import get_settings

MARCAS = [
    "226ERS", "2XU", "361", "Adidas", "Altra", "Anta", "Arc'teryx",
    "ARCh MAX", "ASICS", "Asolo", "Atom", "Atreyu", "Barefoot", "Best",
    "Bestard", "Black Diamond", "BMAI", "Boreal", "Brooks", "Buff",
    "Bussetus", "Camelbak", "Camp", "Carb Boom", "Casio", "Cébé", "Cep",
    "Chiruca", "CimAlp", "Coleman", "Columbia", "Compressport", "Coros",
    "Craft", "dhb", "Diadora", "Duo Tonic", "Dynafit", "Eassun", "Ecco",
    "Eider", "Enda", "Enforma", "Equarea", "Feetures!", "Fenix", "Fila",
    "Fyke", "Garmin", "Garmont", "Gore Running Wear", "Gore-Tex", "Grifone",
    "Gu Energy", "Haglöfs", "Health", "Helly Hansen", "Hi-Tec", "High5",
    "Hoka", "Hoko", "Houdini", "Hylo", "Icebreaker", "Icebug", "Injinji",
    "Inov-8", "Isostar", "Jack Wolfskin", "Joluvi", "Joma", "K-Swiss",
    "Kalenji", "Kamuabu", "Karhu", "Keepgoing", "Kelme", "Kiprun", "KJUS",
    "Komperdell", "La Sportiva", "LaFuma", "Land", "Led Lenser", "LedWave",
    "Leki", "Li-Ning", "Loffler", "Lorpen", "Lupine", "Lurbel", "Mammut",
    "Marmot", "Maxim", "Merrell", "Millet", "Mizuno", "Monk", "Monroad",
    "Montane", "Mount to Coast", "Mountain Hardwear", "Mund", "Mystic Wear",
    "Naak", "Naked", "Nathan", "New Balance", "Newton Running", "Nike",
    "NutriSport", "Oboz", "Odlo", "Olympikus", "On", "Onemix", "OS2O",
    "Overstims", "Oxsitis", "Patagonia", "Petzl", "Plantronics", "Podoks",
    "Polar", "Polartec", "Polygiene", "Powerbar", "PrimaLoft",
    "Princeton Tec", "Puma", "Qiaodan", "Quechua", "Rab", "RaidLight",
    "Reebok", "Ronhill", "Salming", "Salomon", "Saucony", "Saxx Underwear",
    "Scarpa", "Science in Sport", "Scott", "Silva", "Sizen", "Skechers",
    "Skins", "SPIbelt", "Squeezy", "Suunto", "Tecnica", "Tenth", "Ternua",
    "Teva", "The North Face", "The Second Skin Underwear", "TomTom",
    "Topo Athletic", "Torq", "Totum Sport", "TrangoWorld", "TYR", "U-Tech",
    "UK Gear", "Ultimate Direction", "Ulysses", "Under Armour", "USN",
    "UYN", "Varta", "Vasque", "Veja", "Veriga", "Vibram Fivefingers",
    "Victory Endurance", "Viking", "Vivobarefoot", "WAA", "Walsh", "Wiggle",
    "Wong", "Wrightsock", "X-Bionic", "X-Socks", "Xtep", "Zara", "Zoot",
]

def main():
    settings = get_settings()
    engine = create_db_engine(settings.db_url)
    init_db(engine)

    with Session(engine) as db:
        medio = db.query(Medio).filter(Medio.slug == "roadrunningreview").first()
        if not medio:
            print("ERROR: No se encuentra el medio 'roadrunningreview'.")
            print("Créalo primero desde el panel web y vuelve a ejecutar este script.")
            sys.exit(1)

        insertadas = 0
        saltadas = 0

        for nombre in MARCAS:
            existe = db.query(Marca).filter(
                Marca.medio_id == medio.id,
                Marca.nombre_canonico == nombre
            ).first()

            if existe:
                saltadas += 1
                continue

            db.add(Marca(
                medio_id=medio.id,
                nombre_canonico=nombre,
                estado=EstadoEntidadEnum.activa,
            ))
            insertadas += 1

        db.commit()
        print(f"\nResultado para medio '{medio.nombre}':")
        print(f"  Marcas insertadas: {insertadas}")
        print(f"  Ya existían (saltadas): {saltadas}")
        print(f"  Total en BD: {insertadas + saltadas}")
        print("\nListo. Ahora puedes ver las marcas en el panel web.")

if __name__ == "__main__":
    main()