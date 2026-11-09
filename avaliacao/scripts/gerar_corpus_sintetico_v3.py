from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEV_OUTPUT = ROOT / "avaliacao" / "datasets" / "desenvolvimento_sintetico_v3.jsonl"
DEV_MANIFEST = ROOT / "avaliacao" / "datasets" / "desenvolvimento_sintetico_v3_manifest.json"
LOCKED_OUTPUT = ROOT / "avaliacao" / "datasets" / "desafio_sintetico_bloqueado_v3.jsonl"
LOCKED_MANIFEST = ROOT / "avaliacao" / "datasets" / "desafio_sintetico_bloqueado_v3_manifest.json"
LEGACY_REFERENCE = ROOT / "avaliacao" / "datasets" / "corpus_v3_teste.jsonl"
SEED = 20260910
GENERATED_AT = "2026-09-10T00:00:00Z"
CLASS_LABELS = ("OBRA", "DEMO", "SOB_DEMANDA", "TRIAGEM_MANUAL")
CLASS_TARGET = 100
DEDUP_TARGETS = {"positive": 186, "complete_negative": 97, "critical_negative": 75}
LOCATIONS = (
    "Bloco Alfa sala 101", "Bloco Beta laboratório 2", "Biblioteca central",
    "Restaurante estudantil", "Pavilhão de ensino C", "Unidade rural experimental",
    "Prédio administrativo", "Oficina de manutenção", "Ginásio do campus",
    "Residência estudantil", "Centro de pesquisa aplicada", "Portaria principal",
)
REQUESTERS = ("docente", "técnica de laboratório", "servidor administrativo", "estudante", "fiscal de contrato")
CATEGORIES = (
    "Manutenção Predial", "Elétrica", "Hidráulica", "Carpintaria / Marcenaria",
    "Mecânica Geral", "Limpeza e Jardinagem", "Suporte a Serviços Terceirizados",
)


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def visible_hash(record: dict[str, Any]) -> str:
    visible = " ".join(str(record.get(key) or "").casefold().strip() for key in ("title", "content", "location", "category"))
    return canonical_hash(" ".join(visible.split()))


CLASS_ASSETS: dict[str, tuple[tuple[str, str], ...]] = {
    "OBRA": (
        ("centro de tutoria", "Manutenção Predial"), ("galpão patrimonial", "Manutenção Predial"),
        ("guarita secundária", "Manutenção Predial"), ("ala de laboratórios", "Manutenção Predial"),
        ("refeitório estudantil", "Manutenção Predial"), ("auditório acadêmico", "Manutenção Predial"),
        ("passarela entre blocos", "Manutenção Predial"), ("reserva técnica da biblioteca", "Manutenção Predial"),
        ("bloco sanitário", "Manutenção Predial"), ("quadra esportiva", "Manutenção Predial"),
        ("pavilhão agropecuário", "Manutenção Predial"), ("residência estudantil", "Manutenção Predial"),
        ("cozinha institucional", "Manutenção Predial"), ("escada entre pavimentos", "Manutenção Predial"),
        ("rampa acessível", "Manutenção Predial"), ("reservatório elevado", "Hidráulica"),
        ("rede sanitária principal", "Hidráulica"), ("macrodrenagem do setor", "Hidráulica"),
        ("subestação elétrica", "Elétrica"), ("muro de contenção", "Manutenção Predial"),
    ),
    "DEMO": (
        ("luminária de teto", "Elétrica"), ("tomada de bancada", "Elétrica"),
        ("disjuntor de circuito", "Elétrica"), ("interruptor de parede", "Elétrica"),
        ("torneira do lavatório", "Hidráulica"), ("válvula de descarga", "Hidráulica"),
        ("ralo do banheiro", "Hidráulica"), ("sifão da copa", "Hidráulica"),
        ("telha cerâmica", "Manutenção Predial"), ("calha do corredor", "Manutenção Predial"),
        ("placa de forro", "Manutenção Predial"), ("faixa de reboco", "Manutenção Predial"),
        ("fechadura de porta", "Carpintaria / Marcenaria"), ("dobradiça de janela", "Carpintaria / Marcenaria"),
        ("cordão de persiana", "Carpintaria / Marcenaria"), ("solda do corrimão", "Mecânica Geral"),
        ("peça de piso", "Manutenção Predial"), ("vidro de janela", "Carpintaria / Marcenaria"),
        ("canteiro do acesso", "Limpeza e Jardinagem"), ("grade de proteção", "Mecânica Geral"),
    ),
    "SOB_DEMANDA": (
        ("elevador de passageiros", "Suporte a Serviços Terceirizados"), ("plataforma elevatória", "Suporte a Serviços Terceirizados"),
        ("ar-condicionado central", "Suporte a Serviços Terceirizados"), ("câmara fria", "Suporte a Serviços Terceirizados"),
        ("autoclave laboratorial", "Suporte a Serviços Terceirizados"), ("centrífuga refrigerada", "Suporte a Serviços Terceirizados"),
        ("microscópio eletrônico", "Suporte a Serviços Terceirizados"), ("espectrofotômetro", "Suporte a Serviços Terceirizados"),
        ("grupo gerador", "Suporte a Serviços Terceirizados"), ("nobreak central", "Suporte a Serviços Terceirizados"),
        ("inversor fotovoltaico", "Suporte a Serviços Terceirizados"), ("central de alarme", "Suporte a Serviços Terceirizados"),
        ("câmera de vigilância", "Suporte a Serviços Terceirizados"), ("leitor de acesso", "Suporte a Serviços Terceirizados"),
        ("portão automático", "Suporte a Serviços Terceirizados"), ("caldeira didática", "Suporte a Serviços Terceirizados"),
        ("exaustor industrial", "Suporte a Serviços Terceirizados"), ("compressor industrial", "Suporte a Serviços Terceirizados"),
        ("projetor multimídia", "Suporte a Serviços Terceirizados"), ("purificador técnico", "Suporte a Serviços Terceirizados"),
    ),
    "TRIAGEM_MANUAL": (
        ("equipamento não identificado", "Manutenção Predial"), ("ponto de água indefinido", "Hidráulica"),
        ("instalação elétrica genérica", "Elétrica"), ("porta sem componente indicado", "Carpintaria / Marcenaria"),
        ("máquina mencionada por apelido", "Mecânica Geral"), ("cobertura sem escopo", "Manutenção Predial"),
        ("ambiente sem localização", "Manutenção Predial"), ("foto que não foi anexada", "Manutenção Predial"),
        ("patrimônio sem número", "Mecânica Geral"), ("ruído sem origem", "Mecânica Geral"),
        ("odor sem causa", "Hidráulica"), ("calor no ambiente", "Suporte a Serviços Terceirizados"),
        ("parede sem ação definida", "Manutenção Predial"), ("rampa sem histórico", "Manutenção Predial"),
        ("pedido de vistoria geral", "Manutenção Predial"), ("orçamento sem objeto", "Suporte a Serviços Terceirizados"),
        ("vários defeitos misturados", "Manutenção Predial"), ("serviço com dois prédios", "Manutenção Predial"),
        ("chamado com estados contraditórios", "Manutenção Predial"), ("solicitação fora do domínio físico", "Manutenção Predial"),
    ),
}

CLASS_MECHANISMS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "OBRA": (
        ("implantação inédita", "construir {asset} em terreno livre", "exige fundações, estrutura, cobertura e instalações novas"),
        ("ampliação física", "ampliar {asset} além da fachada atual", "a área edificada aumentará com fundações e fechamento novos"),
        ("alteração estrutural", "reconfigurar estruturalmente {asset}", "o projeto altera lajes, pilares ou vigas do sistema resistente"),
        ("reconstrução integral", "demolir e reconstruir integralmente {asset}", "o sistema existente será substituído por solução construtiva redesenhada"),
        ("infraestrutura principal", "implantar infraestrutura permanente para {asset}", "o serviço cria redes principais e capacidade que hoje não existem"),
    ),
    "DEMO": (
        ("troca localizada", "substituir componente danificado de {asset}", "somente a peça avariada será trocada, preservando a instalação"),
        ("reparo pontual", "reparar a falha localizada em {asset}", "não haverá ampliação, novo circuito ou alteração estrutural"),
        ("ajuste funcional", "ajustar {asset} que perdeu alinhamento ou regulagem", "o item existente será mantido após ajuste simples"),
        ("limpeza técnica simples", "limpar e desobstruir {asset}", "a intervenção cotidiana não muda traçado, capacidade ou estrutura"),
        ("recomposição superficial", "recompor acabamento ou fixação de {asset}", "o trabalho fica restrito à superfície e aos fixadores existentes"),
    ),
    "SOB_DEMANDA": (
        ("diagnóstico especializado", "diagnosticar falha interna em {asset}", "exige instrumentação e assistência técnica especializada"),
        ("calibração certificada", "calibrar e certificar {asset}", "a rastreabilidade metrológica depende de prestador habilitado"),
        ("garantia do fabricante", "acionar a garantia para {asset}", "intervenção interna cancelaria a cobertura do fabricante"),
        ("contrato de manutenção", "abrir atendimento contratual para {asset}", "o ativo está coberto por manutenção terceirizada obrigatória"),
        ("segurança regulamentada", "corrigir falha de segurança em {asset}", "norma e risco do equipamento exigem técnico legalmente habilitado"),
    ),
    "TRIAGEM_MANUAL": (
        ("objeto ausente", "resolver o problema relacionado a {asset}", "não há identificação suficiente do objeto nem do defeito"),
        ("escopo contraditório", "fazer reparo simples e reconstrução completa em {asset}", "o relato combina escopos incompatíveis sem indicar qual é correto"),
        ("múltiplos serviços", "atender {asset} junto com outras ocorrências", "ativos, locais e prioridades não foram separados"),
        ("local ou responsável ausente", "providenciar atendimento para {asset}", "não há local verificável nem informação para definir o executor"),
        ("evidência referenciada ausente", "corrigir {asset} conforme anexo", "o anexo não existe e o texto não contém sintoma ou ação verificável"),
    ),
}

LOCKED_CLASS_ASSETS: dict[str, tuple[tuple[str, str], ...]] = {
    "OBRA": (
        ("herbário climatizado", "Manutenção Predial"),
        ("centro de convivência coberto", "Manutenção Predial"),
        ("laboratório de sementes", "Manutenção Predial"),
        ("estação de tratamento experimental", "Hidráulica"),
        ("abrigo para veículos oficiais", "Manutenção Predial"),
    ),
    "DEMO": (
        ("trinco do armário", "Carpintaria / Marcenaria"),
        ("espelho de tomada", "Elétrica"),
        ("joelho da tubulação", "Hidráulica"),
        ("tela de proteção", "Mecânica Geral"),
        ("rejunte do piso", "Manutenção Predial"),
    ),
    "SOB_DEMANDA": (
        ("cromatógrafo líquido", "Suporte a Serviços Terceirizados"),
        ("cabine de segurança biológica", "Suporte a Serviços Terceirizados"),
        ("analisador de energia", "Suporte a Serviços Terceirizados"),
        ("sistema de osmose reversa", "Suporte a Serviços Terceirizados"),
        ("incubadora de CO2", "Suporte a Serviços Terceirizados"),
    ),
    "TRIAGEM_MANUAL": (
        ("instalação citada em áudio ausente", "Manutenção Predial"),
        ("objeto chamado apenas de módulo", "Mecânica Geral"),
        ("ocorrência com referência espacial incompleta", "Manutenção Predial"),
        ("pedido misto de compra e reparo", "Suporte a Serviços Terceirizados"),
        ("componente com duas numerações", "Manutenção Predial"),
    ),
}

DEDUP_ASSETS = (
    ("torneira do lavatório", "vazamento no registro", "Hidráulica"), ("luminária do corredor", "não acende", "Elétrica"),
    ("fechadura da sala", "trava ao girar", "Carpintaria / Marcenaria"), ("calha do bloco", "transborda na chuva", "Manutenção Predial"),
    ("tomada da bancada", "sem energia", "Elétrica"), ("sifão da copa", "goteja na conexão", "Hidráulica"),
    ("persiana lateral", "cordão rompido", "Carpintaria / Marcenaria"), ("placa de forro", "está cedendo", "Manutenção Predial"),
    ("ralo do banheiro", "permanece obstruído", "Hidráulica"), ("disjuntor do laboratório", "desarma ao ligar", "Elétrica"),
    ("janela da secretaria", "não fecha", "Carpintaria / Marcenaria"), ("corrimão da escada", "fixação solta", "Mecânica Geral"),
    ("telha sobre a biblioteca", "está trincada", "Manutenção Predial"), ("interruptor da entrada", "tecla quebrada", "Elétrica"),
    ("válvula de descarga", "não veda", "Hidráulica"), ("porta do arquivo", "raspa no piso", "Carpintaria / Marcenaria"),
    ("grade do depósito", "solda abriu", "Mecânica Geral"), ("piso da circulação", "peça está solta", "Manutenção Predial"),
    ("reboco da fachada", "desprendeu", "Manutenção Predial"), ("bancada do laboratório", "fixação balança", "Mecânica Geral"),
    ("bebedouro do pátio", "água escorre", "Hidráulica"), ("luminária de emergência", "bateria não mantém carga", "Elétrica"),
    ("registro do jardim", "não fecha", "Hidráulica"), ("portinhola do quadro", "dobradiça soltou", "Mecânica Geral"),
    ("vedação da janela", "entra água", "Manutenção Predial"), ("maçaneta do auditório", "está frouxa", "Carpintaria / Marcenaria"),
    ("canaleta elétrica", "tampa desencaixou", "Elétrica"), ("grelha de drenagem", "acumula resíduos", "Hidráulica"),
    ("rodapé da sala", "descolou", "Manutenção Predial"), ("mola da porta", "não retorna", "Carpintaria / Marcenaria"),
    ("suporte do extintor", "fixação rompeu", "Mecânica Geral"),
)

COMPLETE_NEGATIVE_ASSETS = DEDUP_ASSETS[:19]
CRITICAL_ASSETS = DEDUP_ASSETS[16:31]


def base_record(*, case_id: str, scenario_id: str, episode_id: str, dimension: str,
                order: int, title: str, content: str, category: str, location: str,
                group_hash: str, semantic_signature: dict[str, Any], template_lineage: str,
                split: str, scenario_set: str, occurrence: datetime) -> dict[str, Any]:
    record = {
        "case_id": case_id, "scenario_id": scenario_id, "group_id": scenario_id,
        "episode_id": episode_id, "dimension": dimension, "order_in_group": order,
        "order_in_episode": order, "title": title, "content": content, "category": category,
        "location": location, "requester": REQUESTERS[int(group_hash[:4], 16) % len(REQUESTERS)],
        "urgency": 1 + int(group_hash[4:6], 16) % 5, "impact": 1 + int(group_hash[6:8], 16) % 5,
        "status": 1, "template_family": f"{scenario_set}_{template_lineage}",
        "narrative_core": canonical_hash(semantic_signature)[:24],
        "narrative_core_sha256": canonical_hash({"core": semantic_signature}),
        "source_dependency_group_sha256": group_hash,
        "generator_lineage_sha256": canonical_hash({"scenario_set": scenario_set, "lineage": template_lineage}),
        "semantic_signature": semantic_signature, "surface_realization": f"R{order:02d}",
        "dataset_version": "3.0.0", "scenario_set": scenario_set, "split": split,
        "generation_seed": SEED, "occurrence_at": occurrence.isoformat(),
        "label_source": "REGRA_SINTETICA_PRE_REGISTRADA", "gold_status": "ROTULO_PROXY_NAO_INSTITUCIONAL",
        "synthetic": True, "pilot_only": True, "confirmatory_eligible": False,
        "source_contains_personal_data": False, "category_intentionally_incorrect": False,
        "policy_source": "avaliacao/config/plano_cientifico_preimplantacao_v5.json",
    }
    record["visible_text_sha256"] = visible_hash(record)
    return record


def classification_groups(*, locked: bool) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    split = "TESTE" if locked else "DESENVOLVIMENTO"
    scenario_set = "SYNTHETIC_LOCKED_CHALLENGE_V3" if locked else "SYNTHETIC_DEVELOPMENT_V3"
    assets_per_class = 5 if locked else 20
    base_time = datetime(2025, 3 if locked else 1, 1, tzinfo=timezone.utc)
    serial = 0
    for label in CLASS_LABELS:
        selected = LOCKED_CLASS_ASSETS[label] if locked else CLASS_ASSETS[label]
        if len(selected) != assets_per_class:
            raise ValueError(f"Catálogo classificatório inválido para {label}")
        for asset_index, (asset, category) in enumerate(selected):
            for mechanism_index, (mechanism, request, evidence) in enumerate(CLASS_MECHANISMS[label]):
                signature = {
                    "task": "classification", "label": label, "asset": asset,
                    "decision_mechanism": mechanism,
                    "challenge_partition": "locked" if locked else "development",
                }
                group_hash = canonical_hash(signature)
                scenario_id = f"{'LOCK' if locked else 'DEV'}_CLS_{label}_{asset_index:02d}_{mechanism_index:02d}"
                location = LOCATIONS[(asset_index * 3 + mechanism_index + (7 if locked else 0)) % len(LOCATIONS)]
                if label in {"OBRA", "SOB_DEMANDA"}:
                    # Evita que o roteador determinístico retire estes casos do
                    # estrato realmente encaminhado ao classificador. A ausência
                    # do campo de local não cria uma família nova nem muda o gold.
                    location = ""
                group: list[dict[str, Any]] = []
                variants = 1 if locked else 2
                for variation in range(variants):
                    serial += 1
                    wording = request.format(asset=asset)
                    proof = evidence.format(asset=asset)
                    if label == "OBRA":
                        wording = f"Construir {asset} em terreno livre"
                        proof = f"O projeto cria área edificada permanente com fundação própria na modalidade {mechanism}"
                    elif label == "SOB_DEMANDA":
                        recognized = "elevador auxiliar" if asset == "plataforma elevatória" else asset
                        if locked:
                            recognized = f"autoclave auxiliar vinculada a {asset}"
                        wording = f"O {recognized} apresenta falha funcional"
                        proof = f"O atendimento exige diagnóstico do fabricante e serviço especializado na modalidade {mechanism}"
                    elif label == "TRIAGEM_MANUAL":
                        wording = f"Uma porta apresenta falha em ocorrência associada a {asset}"
                        proof = f"O local é conhecido, mas a condição {mechanism} impede definir a modalidade e exige triagem humana"
                    elif locked:
                        wording = f"Reparar de forma localizada uma porta associada a {asset}"
                        proof = f"A intervenção simples preserva a instalação existente na modalidade {mechanism}"
                    if variation:
                        wording = f"{wording}; a solicitação foi confirmada em nova inspeção"
                        proof = f"Detalhe complementar sem alterar o núcleo: {proof}"
                    record = base_record(
                        case_id=f"{'LOCK' if locked else 'DEV'}-V3-C-{serial:05d}",
                        scenario_id=scenario_id, episode_id=scenario_id, dimension="CLASSIFICACAO",
                        order=variation + 1, title=f"{mechanism}: {asset}",
                        content=f"{wording}. {proof}.", category=category, location=location,
                        group_hash=group_hash, semantic_signature=signature,
                        template_lineage=f"CLS_{label}_{mechanism_index:02d}", split=split,
                        scenario_set=scenario_set, occurrence=base_time + timedelta(hours=serial * 3),
                    )
                    record.update({
                        "expected_dedup": None, "reference_case_id": "", "contrast_anchor_case_id": "",
                        "expected_classification": label,
                        "expected_executor": "FISCAL" if label == "OBRA" else "DEMO" if label == "DEMO" else "TERCEIRIZADA" if label == "SOB_DEMANDA" else "TRIAGEM_MANUAL",
                        "expected_status": "PENDENTE", "pair_role": "CLASSIFICATION",
                        "requires_human_review": label == "TRIAGEM_MANUAL",
                        "information_completeness": "INSUFICIENTE" if label == "TRIAGEM_MANUAL" else "COMPLETA",
                        "label_completeness": "CLASSIFICACAO_APENAS",
                        "rationale": f"Regra sintética da classe {label}: {mechanism}.",
                    })
                    record["visible_text_sha256"] = visible_hash(record)
                    group.append(record)
                groups.append(group)
    return groups


POSITIVE_RELATIONS = (
    "explicit_prior_reference", "different_requester_same_event", "added_detail_same_fault",
    "noisy_alias_same_asset", "missing_location_with_exact_reference", "unresolved_continuation",
)
COMPLETE_NEGATIVE_RELATIONS = (
    "different_asset_same_room", "same_asset_different_fault", "same_fault_different_location",
    "resolved_then_new_event", "similar_title_different_tag", "related_component_distinct_fault",
)
CRITICAL_RELATIONS = (
    "location_missing_no_reference", "generic_fault_without_asset_tag", "conflicting_identifiers",
    "multiple_possible_anchors", "resolution_state_unknown",
)


def dedup_pair(asset: str, fault: str, relation: str, location: str, other: str, index: int) -> tuple[str, str, str, str]:
    tag = f"PAT-{1000 + index}"
    anchor = f"O {asset} apresenta {fault}; patrimônio {tag}; ocorrência em {location}."
    if relation == "explicit_prior_reference":
        current = f"Dar continuidade ao chamado anterior: o mesmo {asset}, patrimônio {tag}, continua com {fault}."
    elif relation == "different_requester_same_event":
        current = f"Outro usuário confirmou que o {asset} de patrimônio {tag} segue com {fault} no mesmo ponto."
    elif relation == "added_detail_same_fault":
        current = f"Complemento do relato: no mesmo {asset} {tag}, o problema de {fault} ocorre após alguns minutos."
    elif relation == "noisy_alias_same_asset":
        current = f"Reforço: equip. {tag}, o msm {asset}, ainda está com {fault}; favor juntar ao pedido aberto."
    elif relation == "missing_location_with_exact_reference":
        current = f"O chamado anterior do patrimônio {tag} continua aberto: {asset} com {fault}."
    elif relation == "unresolved_continuation":
        current = f"Atendimento não resolveu; poucas horas depois o mesmo {asset} {tag} permanece com {fault}."
    elif relation == "different_asset_same_room":
        current = f"Outro {asset}, patrimônio PAT-{3000 + index}, apresenta {fault} no mesmo ambiente."
    elif relation == "same_asset_different_fault":
        current = f"O {asset} {tag} agora apresenta um defeito diferente: ruído e travamento, não {fault}."
    elif relation == "same_fault_different_location":
        current = f"Um {asset} em {other} apresenta {fault}; não é o equipamento de {location}."
    elif relation == "resolved_then_new_event":
        current = f"O reparo do {asset} {tag} foi concluído; semanas depois surgiu nova ocorrência de {fault}."
    elif relation == "similar_title_different_tag":
        current = f"Mesmo título, porém o pedido atual é do {asset} patrimônio PAT-{5000 + index}, com {fault}."
    elif relation == "related_component_distinct_fault":
        current = f"No mesmo sistema, outro componente associado ao {asset} falhou; não é o ponto {tag}."
    elif relation == "location_missing_no_reference":
        current = f"Há um {asset} com {fault}, mas não foi informado local, patrimônio ou vínculo com o relato anterior."
    elif relation == "generic_fault_without_asset_tag":
        current = f"Informaram apenas que algo parecido está com {fault}; não há ativo, número ou local verificável."
    elif relation == "conflicting_identifiers":
        current = f"O texto cita {asset} {tag} e também PAT-{7000 + index} em outro prédio, sem indicar qual precisa de serviço."
    elif relation == "multiple_possible_anchors":
        current = f"Há {fault} em um {asset}, mas existem vários chamados semelhantes e nenhum identificador foi fornecido."
    elif relation == "resolution_state_unknown":
        current = f"O {asset} voltou a apresentar {fault}, porém não se sabe se o atendimento anterior foi encerrado ou nunca executado."
    else:
        raise ValueError(relation)
    current_location = "" if relation in {"missing_location_with_exact_reference", *CRITICAL_RELATIONS} else (other if relation == "same_fault_different_location" else location)
    return anchor, current, tag, current_location


def dedup_groups(*, locked: bool) -> list[list[dict[str, Any]]]:
    split = "TESTE" if locked else "DESENVOLVIMENTO"
    scenario_set = "SYNTHETIC_LOCKED_CHALLENGE_V3" if locked else "SYNTHETIC_DEVELOPMENT_V3"
    base_time = datetime(2025, 4 if locked else 2, 1, tzinfo=timezone.utc)
    recipes: list[tuple[str, tuple[str, str, str], str]] = []
    if locked:
        locked_assets = tuple((f"subsistema de ensaio {i + 1}", f"falha funcional tipo {chr(65 + i % 10)}", CATEGORIES[i % len(CATEGORIES)]) for i in range(12))
        recipes.extend(("positive", asset, relation) for asset in locked_assets[:8] for relation in POSITIVE_RELATIONS[:4])
        recipes.extend(("complete_negative", asset, relation) for asset in locked_assets[2:8] for relation in COMPLETE_NEGATIVE_RELATIONS[:4])
        recipes.extend(("critical_negative", asset, relation) for asset in locked_assets[7:12] for relation in CRITICAL_RELATIONS[:3])
    else:
        recipes.extend(("positive", asset, relation) for asset in DEDUP_ASSETS for relation in POSITIVE_RELATIONS)
        complete = [("complete_negative", asset, relation) for asset in COMPLETE_NEGATIVE_ASSETS for relation in COMPLETE_NEGATIVE_RELATIONS]
        recipes.extend(complete[:DEDUP_TARGETS["complete_negative"]])
        recipes.extend(("critical_negative", asset, relation) for asset in CRITICAL_ASSETS for relation in CRITICAL_RELATIONS)
    groups: list[list[dict[str, Any]]] = []
    for index, (stratum, (asset, fault, category), relation) in enumerate(recipes):
        expected = stratum == "positive"
        critical = stratum == "critical_negative"
        location = LOCATIONS[(index * 5 + (3 if locked else 0)) % len(LOCATIONS)]
        other = LOCATIONS[(index * 5 + 7) % len(LOCATIONS)]
        signature = {
            "task": "deduplication", "stratum": stratum, "asset": asset,
            "fault": fault, "event_relation": relation,
            "challenge_partition": "locked" if locked else "development",
        }
        group_hash = canonical_hash(signature)
        scenario_id = f"{'LOCK' if locked else 'DEV'}_DD_{stratum.upper()}_{index + 1:04d}"
        anchor_text, current_text, tag, current_location = dedup_pair(asset, fault, relation, location, other, index)
        anchor_id = f"{'LOCK' if locked else 'DEV'}-V3-D-{index + 1:05d}-A"
        anchor = base_record(
            case_id=anchor_id, scenario_id=scenario_id, episode_id=scenario_id,
            dimension="DEDUPLICACAO", order=1, title=f"{asset}: {fault}", content=anchor_text,
            category=category, location=location, group_hash=group_hash,
            semantic_signature=signature, template_lineage=f"DD_{stratum}_{relation}",
            split=split, scenario_set=scenario_set, occurrence=base_time + timedelta(hours=index * 8),
        )
        anchor.update({
            "expected_dedup": None, "reference_case_id": "", "contrast_anchor_case_id": "",
            "expected_classification": "", "expected_executor": "", "expected_status": "",
            "pair_role": "ANCHOR", "dedup_family": relation, "dedup_stratum": stratum,
            "hard_negative": False, "requires_human_review": False,
            "information_completeness": "COMPLETA", "label_completeness": "ANCORA_SEM_ROTULO_DEDUP",
            "rationale": "Âncora sintética; não compõe a métrica como caso rotulado.", "asset_tag": tag,
        })
        anchor["visible_text_sha256"] = visible_hash(anchor)
        current = base_record(
            case_id=f"{'LOCK' if locked else 'DEV'}-V3-D-{index + 1:05d}-C",
            scenario_id=scenario_id, episode_id=scenario_id, dimension="DEDUPLICACAO", order=2,
            title=f"Reavaliação de {asset}", content=current_text, category=category,
            location=current_location, group_hash=group_hash, semantic_signature=signature,
            template_lineage=f"DD_{stratum}_{relation}", split=split, scenario_set=scenario_set,
            occurrence=base_time + timedelta(hours=index * 8, minutes=47),
        )
        current.update({
            "expected_dedup": expected, "reference_case_id": anchor_id,
            "contrast_anchor_case_id": anchor_id, "expected_classification": "",
            "expected_executor": "", "expected_status": "", "pair_role": "CHALLENGE",
            "dedup_family": relation, "dedup_stratum": stratum, "hard_negative": not expected,
            "requires_human_review": critical,
            "information_completeness": "INSUFICIENTE" if critical else "COMPLETA",
            "label_completeness": "DEDUP_APENAS",
            "rationale": "Mesmo evento e ativo com vínculo suficiente." if expected else "Evento, ativo ou evidência não permitem agrupamento automático.",
            "asset_tag": tag,
        })
        current["visible_text_sha256"] = visible_hash(current)
        groups.append([anchor, current])
    return groups


def flatten_shuffled(groups: list[list[dict[str, Any]]], seed: int) -> list[dict[str, Any]]:
    copied = list(groups)
    random.Random(seed).shuffle(copied)
    return [record for group in copied for record in group]


def overlap(left: Iterable[dict[str, Any]], right: Iterable[dict[str, Any]], field: str) -> int:
    a = {json.dumps(row.get(field), ensure_ascii=False, sort_keys=True) if isinstance(row.get(field), dict) else str(row.get(field) or "") for row in left} - {""}
    b = {json.dumps(row.get(field), ensure_ascii=False, sort_keys=True) if isinstance(row.get(field), dict) else str(row.get(field) or "") for row in right} - {""}
    return len(a & b)


def validate(records: list[dict[str, Any]], *, locked: bool) -> dict[str, Any]:
    class_rows = [row for row in records if row["pair_role"] == "CLASSIFICATION"]
    challenges = [row for row in records if row["pair_role"] == "CHALLENGE"]
    class_groups: dict[str, set[str]] = defaultdict(set)
    for row in class_rows:
        class_groups[row["expected_classification"]].add(row["source_dependency_group_sha256"])
    strata: dict[str, set[str]] = defaultdict(set)
    for row in challenges:
        strata[row["dedup_stratum"]].add(row["source_dependency_group_sha256"])
    if not locked:
        if {label: len(class_groups[label]) for label in CLASS_LABELS} != {label: CLASS_TARGET for label in CLASS_LABELS}:
            raise ValueError("Meta de 100 famílias por classe não atendida")
        if {key: len(strata[key]) for key in DEDUP_TARGETS} != DEDUP_TARGETS:
            raise ValueError("Metas de famílias de deduplicação não atendidas")
    all_groups = [row["source_dependency_group_sha256"] for row in records]
    group_labels: dict[str, set[str]] = defaultdict(set)
    for row in class_rows:
        group_labels[row["source_dependency_group_sha256"]].add(row["expected_classification"])
    for row in challenges:
        group_labels[row["source_dependency_group_sha256"]].add("DUPLICADO" if row["expected_dedup"] else "NAO_DUPLICADO")
    if any(len(labels) != 1 for labels in group_labels.values()):
        raise ValueError("Grupo com rótulos impuros")
    if len({row["visible_text_sha256"] for row in records}) != len(records):
        raise ValueError("Texto visível duplicado")
    return {
        "status": "PASS",
        "records": len(records),
        "classification_groups_by_class": {label: len(class_groups[label]) for label in CLASS_LABELS},
        "dedup_groups_by_stratum": {key: len(strata[key]) for key in sorted(strata)},
        "source_dependency_groups": len(set(all_groups)),
        "group_label_purity": True,
        "unique_visible_texts": len(records),
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records), encoding="utf-8", newline="\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_manifest(path: Path, records: list[dict[str, Any]], validation: dict[str, Any], *, locked: bool,
                   cross_overlap: dict[str, int], legacy_overlap: dict[str, int]) -> dict[str, Any]:
    return {
        "schema_version": "3.0.0", "generated_at": GENERATED_AT,
        "dataset_version": "3.0.0", "scenario_set": "SYNTHETIC_LOCKED_CHALLENGE_V3" if locked else "SYNTHETIC_DEVELOPMENT_V3",
        "split": "TESTE" if locked else "DESENVOLVIMENTO", "status": "FROZEN_LOCKED_SYNTHETIC_CHALLENGE" if locked else "SYNTHETIC_DEVELOPMENT_ONLY",
        "synthetic": True, "proxy_labels_only": True, "pilot_only": True,
        "confirmatory_eligible": False, "scientific_result": False, "production_ready": False,
        "selection_access": "FORBIDDEN_UNTIL_MODEL_SELECTION_FROZEN" if locked else "ALLOWED_FOR_NESTED_GROUPED_SELECTION",
        "validation": validation, "overlap_with_other_v3_partition": cross_overlap,
        "overlap_with_legacy_reserved_corpus": legacy_overlap,
        "files": {
            "jsonl": {"path": artifact_path(path), "sha256": sha256_file(path)},
            "generator": {"path": str(Path(__file__).resolve().relative_to(ROOT)), "sha256": sha256_file(Path(__file__).resolve())},
        },
        "grouping": {
            "primary_field": "source_dependency_group_sha256",
            "semantic_signature_recorded": True,
            "generator_lineage_recorded": True,
            "surface_variations_not_counted_as_independent": True,
        },
        "limitations": [
            "Famílias são combinações semânticas sintéticas pré-implantação, não amostra da distribuição real.",
            "Compartilhar gramáticas de geração cria dependência residual registrada por generator_lineage_sha256.",
            "Rótulos proxy não demonstram eficácia institucional, justiça ou prontidão de produção.",
        ],
    }


def generate(dev_output: Path, dev_manifest: Path, locked_output: Path, locked_manifest: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    dev = flatten_shuffled([*classification_groups(locked=False), *dedup_groups(locked=False)], SEED)
    locked = flatten_shuffled([*classification_groups(locked=True), *dedup_groups(locked=True)], SEED + 1)
    dev_validation = validate(dev, locked=False)
    locked_validation = validate(locked, locked=True)
    fields = ("source_dependency_group_sha256", "scenario_id", "template_family", "narrative_core_sha256", "visible_text_sha256", "semantic_signature")
    cross_dev = {field: overlap(dev, locked, field) for field in fields}
    if any(cross_dev.values()):
        raise ValueError(f"Sobreposição desenvolvimento/desafio: {cross_dev}")
    legacy = read_jsonl(LEGACY_REFERENCE)
    legacy_dev = {field: overlap(dev, legacy, field) for field in fields if field != "semantic_signature"}
    legacy_locked = {field: overlap(locked, legacy, field) for field in fields if field != "semantic_signature"}
    if any(legacy_dev.values()) or any(legacy_locked.values()):
        raise ValueError("Sobreposição com corpus reservado legado")
    write_jsonl(dev_output, dev)
    write_jsonl(locked_output, locked)
    dev_payload = build_manifest(dev_output, dev, dev_validation, locked=False, cross_overlap=cross_dev, legacy_overlap=legacy_dev)
    locked_payload = build_manifest(locked_output, locked, locked_validation, locked=True, cross_overlap=cross_dev, legacy_overlap=legacy_locked)
    dev_manifest.write_text(json.dumps(dev_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    locked_manifest.write_text(json.dumps(locked_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return dev_payload, locked_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera corpus V3 sintético com famílias semânticas e desafio bloqueado.")
    parser.add_argument("--dev", type=Path, default=DEV_OUTPUT)
    parser.add_argument("--dev-manifest", type=Path, default=DEV_MANIFEST)
    parser.add_argument("--locked", type=Path, default=LOCKED_OUTPUT)
    parser.add_argument("--locked-manifest", type=Path, default=LOCKED_MANIFEST)
    args = parser.parse_args()
    dev, locked = generate(args.dev, args.dev_manifest, args.locked, args.locked_manifest)
    print(json.dumps({"development": dev["validation"], "locked": locked["validation"], "overlap": dev["overlap_with_other_v3_partition"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
