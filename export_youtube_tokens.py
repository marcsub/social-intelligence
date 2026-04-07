import sys; sys.path.insert(0,'.')
from sqlalchemy.orm import Session
from core.settings import get_settings
from models.database import create_db_engine, TokenCanal, Medio

s = get_settings()
engine = create_db_engine(s.db_url)
with Session(engine) as db:
    medio = db.query(Medio).filter_by(slug='roadrunningreview').first()
    tokens = db.query(TokenCanal).filter(
        TokenCanal.medio_id == medio.id,
        TokenCanal.canal == 'youtube'
    ).all()
    for t in tokens:
        print(f"INSERT INTO token_canal (medio_id, canal, clave, valor_cifrado) VALUES ({t.medio_id}, '{t.canal}', '{t.clave}', '{t.valor_cifrado}') ON DUPLICATE KEY UPDATE valor_cifrado=VALUES(valor_cifrado);")
