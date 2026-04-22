"""
core/brand_id_agent.py
Agente de identificación de marca y agencia por análisis de texto.
Sin IA en Fase 1 — matching de texto contra listas canónicas con aliases.
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session
from models.database import Marca, Agencia, EstadoEntidadEnum


@dataclass
class BrandIdResult:
    marca_id: Optional[int] = None
    marca_nombre: Optional[str] = None
    agencia_id: Optional[int] = None
    agencia_nombre: Optional[str] = None
    marcas_secundarias: list[dict] = field(default_factory=list)
    confianza: int = 0
    razonamiento: str = ""


def _normalize(text: str) -> str:
    """Normaliza texto: minúsculas, sin tildes ni diéresis, sin @/#."""
    import unicodedata
    text = text.lower().strip()
    # Quita tildes, diéresis, acentos en general (NFKD + drop combining marks)
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )
    text = re.sub(r"[@#]", "", text)
    return text


def _extract_tokens(text: str) -> set[str]:
    """Extrae tokens del texto: palabras, hashtags, menciones."""
    if not text:
        return set()
    normalized = _normalize(text)
    # Palabras simples + bigramas para nombres compuestos
    words = re.findall(r"\b\w+\b", normalized)
    tokens = set(words)
    # Bigramas
    for i in range(len(words) - 1):
        tokens.add(f"{words[i]} {words[i+1]}")
    # Trigramas
    for i in range(len(words) - 2):
        tokens.add(f"{words[i]} {words[i+1]} {words[i+2]}")
    return tokens


def _score_entity(entity_name: str, aliases_csv: Optional[str], tokens: set[str]) -> int:
    """
    Calcula puntuación de coincidencia para una entidad (marca o agencia).
    Devuelve 0-100.
    """
    candidates = [_normalize(entity_name)]
    if aliases_csv:
        candidates += [_normalize(a) for a in aliases_csv.split(",") if a.strip()]

    best = 0
    for candidate in candidates:
        if not candidate:
            continue
        if candidate in tokens:
            # Coincidencia exacta
            score = 100 if candidate == _normalize(entity_name) else 90
        elif len(candidate) >= 4 and any(t.startswith(candidate) for t in tokens):
            # Candidato es prefijo de un token (ej: "asics" en "asicsrunning")
            # Solo para candidatos >=4 chars para evitar falsos positivos con nombres
            # muy cortos ("on" en "one", "con", "clifton", etc.)
            score = 70
        elif any(t in candidate for t in tokens if len(t) > 3):
            # Token del texto dentro del nombre de la entidad
            score = 50
        else:
            score = 0
        best = max(best, score)

    return best


def identify(
    medio_id: int,
    db: Session,
    caption: str = "",
    hashtags: str = "",
    mentions: str = "",
    title: str = "",
    description: str = "",
    url: str = "",
) -> BrandIdResult:
    """
    Identifica marca y agencia a partir del texto disponible de una publicación.

    Args:
        medio_id: ID del medio (para cargar sus marcas/agencias)
        db: sesión de base de datos
        caption: texto del caption/cuerpo
        hashtags: hashtags separados por espacio o coma
        mentions: menciones (@cuenta) separadas por espacio
        title: título del artículo o vídeo
        description: descripción larga
        url: URL de la publicación

    Returns:
        BrandIdResult con marca, agencia y nivel de confianza
    """
    # Combinar todo el texto disponible
    full_text = " ".join(filter(None, [caption, hashtags, mentions, title, description, url]))
    tokens = _extract_tokens(full_text)

    if not tokens:
        return BrandIdResult(confianza=0, razonamiento="Sin texto para analizar")

    # Cargar entidades activas del medio
    marcas = db.query(Marca).filter(
        Marca.medio_id == medio_id,
        Marca.estado == EstadoEntidadEnum.activa
    ).all()

    agencias = db.query(Agencia).filter(
        Agencia.medio_id == medio_id,
        Agencia.estado == EstadoEntidadEnum.activa
    ).all()

    # Puntuar marcas
    marca_scores = []
    for marca in marcas:
        score = _score_entity(marca.nombre_canonico, marca.aliases, tokens)
        if score > 0:
            marca_scores.append((marca, score))
    marca_scores.sort(key=lambda x: x[1], reverse=True)

    # Puntuar agencias
    agencia_scores = []
    for agencia in agencias:
        score = _score_entity(agencia.nombre_canonico, agencia.aliases, tokens)
        if score > 0:
            agencia_scores.append((agencia, score))
    agencia_scores.sort(key=lambda x: x[1], reverse=True)

    result = BrandIdResult()

    # Asignar agencia principal
    if agencia_scores:
        best_agencia, ag_score = agencia_scores[0]
        if ag_score >= 50:
            result.agencia_id = best_agencia.id
            result.agencia_nombre = best_agencia.nombre_canonico

    # Asignar marca principal
    if marca_scores:
        best_marca, mk_score = marca_scores[0]
        result.marca_id = best_marca.id
        result.marca_nombre = best_marca.nombre_canonico
        result.confianza = mk_score

        # Marcas secundarias (para comparativas) — score >= 60 y no es la principal
        for marca, score in marca_scores[1:]:
            if score >= 60:
                result.marcas_secundarias.append({
                    "marca_id": marca.id,
                    "nombre": marca.nombre_canonico,
                    "confianza": score
                })

        # Desambiguación: si la agencia detectada tiene como marca habitual
        # la que encontramos, aumentamos la confianza
        if result.agencia_id and best_agencia.marcas_habituales:
            marcas_habituales = [
                _normalize(m) for m in best_agencia.marcas_habituales.split(",")
            ]
            if _normalize(best_marca.nombre_canonico) in marcas_habituales:
                result.confianza = min(100, result.confianza + 10)
                result.razonamiento = (
                    f"Marca '{best_marca.nombre_canonico}' identificada por texto (score {mk_score}) "
                    f"y confirmada por agencia '{best_agencia.nombre_canonico}'"
                )
            else:
                result.razonamiento = (
                    f"Marca '{best_marca.nombre_canonico}' (score {mk_score}), "
                    f"agencia '{best_agencia.nombre_canonico}' detectada"
                )
        else:
            result.razonamiento = f"Marca '{best_marca.nombre_canonico}' identificada por texto (score {mk_score})"

    else:
        # Sin marca — intentar inferir por agencia + marcas habituales
        if result.agencia_id and best_agencia.marcas_habituales:
            marcas_habituales_nombres = [
                m.strip() for m in best_agencia.marcas_habituales.split(",")
            ]
            for nombre in marcas_habituales_nombres:
                marca_candidata = db.query(Marca).filter(
                    Marca.medio_id == medio_id,
                    Marca.nombre_canonico == nombre,
                    Marca.estado == EstadoEntidadEnum.activa
                ).first()
                if marca_candidata:
                    result.marca_id = marca_candidata.id
                    result.marca_nombre = marca_candidata.nombre_canonico
                    result.confianza = 55  # Confianza reducida — inferida por agencia
                    result.razonamiento = (
                        f"Marca inferida por agencia '{best_agencia.nombre_canonico}' "
                        f"(marca habitual: '{nombre}')"
                    )
                    break

        if not result.marca_id:
            result.confianza = 0
            result.razonamiento = "No se pudo identificar la marca en el texto disponible"

    return result
