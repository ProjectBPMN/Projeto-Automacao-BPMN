"""
Popula o GLPI com dados realistas de chamados de manutenção

Cria:
  - Categorias ITIL conforme Regimento Interno (Seção de Serviços)
  - Localizações (setores do campus)
  - Usuários solicitantes (funcionários fictícios)
  - ~120 chamados com cenários variados:
      * Chamados duplicados (mesmo setor + serviço em < 4 semanas)
      * Chamados que são OBRA e não manutenção
      * Chamados com categoria possivelmente errada
      * Variação de status, urgência e datas

Uso:
  1. Suba o GLPI com docker-compose up -d
  2. Acesse http://localhost:9080 e faça login com a conta configurada
  3. Habilite a API REST:
     Configurar > Geral > API
       - Ativar API REST: Sim
       - Ativar login com credenciais: Sim
       - Ativar login com token externo: Sim
  4. Gere um API Token de aplicação em:
     Configurar > Geral > API > (adicionar cliente API)
       - Nome: seed_script
       - Ativo: Sim
       - Token da aplicação: (copie o token gerado)
  5. Execute:
     pip install -r requirements.txt
     python seed_glpi.py --url http://localhost:9080 --app-token SEU_TOKEN --user SEU_USUARIO --password SUA_SENHA
"""

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests



GLPI_DEFAULT_URL = os.getenv("GLPI_URL", "http://localhost:9080")
GLPI_DEFAULT_USER = os.getenv("GLPI_USER", "")
GLPI_DEFAULT_PASS = os.getenv("GLPI_PASSWORD", "")

CATEGORIAS = [
    {
        "name": "Elétrica",
        "comment": "Solução de problemas ligados a instalações elétricas, conservação e manutenção de sistemas elétricos.",
    },
    {
        "name": "Hidráulica",
        "comment": "Solução de problemas em redes e instalações hidráulicas (água, esgoto, tubulações em geral).",
    },
    {
        "name": "Carpintaria / Marcenaria",
        "comment": "Execução e conserto de itens de madeira (mobiliário fixo, portas, esquadrias etc.).",
    },
    {
        "name": "Mecânica Geral",
        "comment": "Serviços de mecânica ligados à infraestrutura do campus (máquinas, equipamentos, sistemas mecânicos).",
    },
    {
        "name": "Manutenção Predial",
        "comment": "Pequenos reparos em alvenaria, ajustes em estruturas existentes, conservação predial em geral.",
    },
    {
        "name": "Limpeza e Jardinagem",
        "comment": "Conservação de áreas externas, jardins, apoio a limpeza e conservação do espaço físico.",
    },
    {
        "name": "Suporte a Serviços Terceirizados",
        "comment": "Acompanhamento e apoio à execução de serviços de apoio contratados (limpeza, vigilância, etc.).",
    },
]


LOCALIZACOES = [
    {"name": "Bloco A - Salas de Aula", "comment": "Prédio principal de salas de aula"},
    {"name": "Bloco B - Laboratórios", "comment": "Laboratórios de ensino e pesquisa"},
    {"name": "Bloco C - Administrativo", "comment": "Setores administrativos e direção"},
    {"name": "Refeitório", "comment": "Restaurante universitário"},
    {"name": "Biblioteca", "comment": "Biblioteca central do campus"},
    {"name": "Ginásio Poliesportivo", "comment": "Espaço esportivo coberto"},
    {"name": "Alojamento Estudantil", "comment": "Moradia dos estudantes internos"},
    {"name": "Auditório", "comment": "Auditório principal do campus"},
    {"name": "Fazenda Escola", "comment": "Área rural e unidades de produção"},
    {"name": "Setor de TI", "comment": "Setor de Tecnologia da Informação"},
    {"name": "Prefeitura do Campus", "comment": "Setor responsável pela manutenção predial"},
    {"name": "Guarita / Portaria", "comment": "Controle de acesso do campus"},
    {"name": "Almoxarifado", "comment": "Depósito de materiais"},
    {"name": "Bloco D - Agroindústria", "comment": "Laboratórios e salas de agroindústria"},
]


USUARIOS = [
    {"name": "maria.silva", "realname": "Silva", "firstname": "Maria", "phone": "(32) 99999-0001"},
    {"name": "joao.santos", "realname": "Santos", "firstname": "João", "phone": "(32) 99999-0002"},
    {"name": "ana.oliveira", "realname": "Oliveira", "firstname": "Ana", "phone": "(32) 99999-0003"},
    {"name": "carlos.souza", "realname": "Souza", "firstname": "Carlos", "phone": "(32) 99999-0004"},
    {"name": "patricia.costa", "realname": "Costa", "firstname": "Patrícia", "phone": "(32) 99999-0005"},
    {"name": "ricardo.lima", "realname": "Lima", "firstname": "Ricardo", "phone": "(32) 99999-0006"},
    {"name": "fernanda.rocha", "realname": "Rocha", "firstname": "Fernanda", "phone": "(32) 99999-0007"},
    {"name": "pedro.almeida", "realname": "Almeida", "firstname": "Pedro", "phone": "(32) 99999-0008"},
    {"name": "lucia.ferreira", "realname": "Ferreira", "firstname": "Lúcia", "phone": "(32) 99999-0009"},
    {"name": "marcos.ribeiro", "realname": "Ribeiro", "firstname": "Marcos", "phone": "(32) 99999-0010"},
]


CHAMADOS_NORMAIS = [
    {"titulo": "Lâmpada queimada na sala 101", "conteudo": "A lâmpada fluorescente da sala 101 está queimada há 3 dias. A sala fica muito escura no período da tarde.", "categoria": "Elétrica", "urgencia": 3},
    {"titulo": "Tomada sem funcionar no laboratório de informática", "conteudo": "A tomada próxima à bancada 3 do laboratório de informática não está funcionando. Não conseguimos ligar os computadores.", "categoria": "Elétrica", "urgencia": 4},
    {"titulo": "Ventilador de teto com defeito", "conteudo": "O ventilador de teto da sala 205 está fazendo barulho e às vezes para de funcionar sozinho.", "categoria": "Elétrica", "urgencia": 2},
    {"titulo": "Curto-circuito no quadro de distribuição", "conteudo": "O disjuntor do corredor do Bloco A está desarmando frequentemente. Parece haver um curto-circuito no circuito de iluminação.", "categoria": "Elétrica", "urgencia": 5},
    {"titulo": "Interruptor quebrado na sala dos professores", "conteudo": "O interruptor de luz da sala dos professores quebrou e está com os fios expostos. Risco de choque.", "categoria": "Elétrica", "urgencia": 5},
    {"titulo": "Fiação exposta no corredor", "conteudo": "Há fiação elétrica exposta no corredor do segundo andar do Bloco B, próximo ao bebedouro. Perigo para os alunos.", "categoria": "Elétrica", "urgencia": 5},
    {"titulo": "Ar-condicionado não liga", "conteudo": "O ar-condicionado da sala de reuniões do setor administrativo não liga. Verificar se é problema elétrico na instalação.", "categoria": "Elétrica", "urgencia": 3},
    {"titulo": "Troca de lâmpadas do estacionamento", "conteudo": "Várias lâmpadas do estacionamento estão queimadas. À noite fica muito escuro e inseguro.", "categoria": "Elétrica", "urgencia": 4},

    {"titulo": "Vazamento no banheiro masculino", "conteudo": "Há um vazamento constante na torneira do banheiro masculino do Bloco A, térreo. Está desperdiçando água.", "categoria": "Hidráulica", "urgencia": 3},
    {"titulo": "Descarga do vaso sanitário não funciona", "conteudo": "A descarga do segundo box do banheiro feminino do Bloco C não está funcionando. Já tem 2 dias.", "categoria": "Hidráulica", "urgencia": 4},
    {"titulo": "Entupimento no ralo do refeitório", "conteudo": "O ralo da cozinha do refeitório está entupido. A água não escoa e está acumulando no chão.", "categoria": "Hidráulica", "urgencia": 5},
    {"titulo": "Cano estourado no alojamento", "conteudo": "Um cano estourou no banheiro do alojamento masculino. Está jorrando água e molhando o corredor.", "categoria": "Hidráulica", "urgencia": 5},
    {"titulo": "Bebedouro sem água", "conteudo": "O bebedouro do segundo andar do Bloco B não está saindo água. Os alunos precisam descer ao térreo.", "categoria": "Hidráulica", "urgencia": 3},
    {"titulo": "Infiltração no teto da biblioteca", "conteudo": "Há uma infiltração no teto da biblioteca que piora quando chove. Está danificando os livros da estante próxima.", "categoria": "Hidráulica", "urgencia": 4},
    {"titulo": "Torneira do laboratório gotejando", "conteudo": "A torneira da pia do laboratório de química está gotejando constantemente, mesmo fechada.", "categoria": "Hidráulica", "urgencia": 2},

    {"titulo": "Porta da sala 302 não fecha", "conteudo": "A porta da sala 302 está com a dobradiça quebrada e não fecha direito. Entra vento e atrapalha as aulas.", "categoria": "Carpintaria / Marcenaria", "urgencia": 3},
    {"titulo": "Carteira quebrada na sala 104", "conteudo": "Uma carteira da sala 104 está com o tampo solto. Um aluno quase se machucou.", "categoria": "Carpintaria / Marcenaria", "urgencia": 4},
    {"titulo": "Armário do almoxarifado com porta emperrada", "conteudo": "O armário grande do almoxarifado está com a porta emperrada. Não conseguimos abrir para pegar materiais.", "categoria": "Carpintaria / Marcenaria", "urgencia": 3},
    {"titulo": "Janela de madeira apodrecida", "conteudo": "A esquadria de madeira da janela do corredor do Bloco A está apodrecida e com risco de cair.", "categoria": "Carpintaria / Marcenaria", "urgencia": 4},
    {"titulo": "Mesa do professor rachada", "conteudo": "A mesa do professor na sala 201 está rachada no meio. Precisa de reparo ou troca.", "categoria": "Carpintaria / Marcenaria", "urgencia": 2},
    {"titulo": "Banco do auditório quebrado", "conteudo": "Três bancos na fileira central do auditório estão com o assento solto.", "categoria": "Carpintaria / Marcenaria", "urgencia": 3},

    {"titulo": "Portão automático travado", "conteudo": "O portão automático da entrada principal travou na posição semifechada. Os veículos não conseguem passar.", "categoria": "Mecânica Geral", "urgencia": 5},
    {"titulo": "Elevador com barulho estranho", "conteudo": "O elevador do Bloco C está fazendo um barulho metálico ao subir. Os funcionários estão com medo de usar.", "categoria": "Mecânica Geral", "urgencia": 4},
    {"titulo": "Bomba d'água com defeito", "conteudo": "A bomba d'água da caixa d'água principal está fazendo barulho e parece que não está bombeando com pressão normal.", "categoria": "Mecânica Geral", "urgencia": 4},
    {"titulo": "Grade do portão lateral solta", "conteudo": "A grade do portão lateral (acesso à fazenda) está com as soldas rompidas.", "categoria": "Mecânica Geral", "urgencia": 3},
    {"titulo": "Motor do exaustor da cozinha", "conteudo": "O motor do exaustor da cozinha do refeitório parou de funcionar. A cozinha está ficando cheia de fumaça.", "categoria": "Mecânica Geral", "urgencia": 5},

    {"titulo": "Rachadura na parede do corredor", "conteudo": "Há uma rachadura visível na parede do corredor do Bloco B, segundo andar. Parece estar aumentando.", "categoria": "Manutenção Predial", "urgencia": 3},
    {"titulo": "Piso solto na entrada do refeitório", "conteudo": "Algumas cerâmicas do piso na entrada do refeitório estão soltas. Alguém pode tropeçar e se machucar.", "categoria": "Manutenção Predial", "urgencia": 4},
    {"titulo": "Goteira no teto da sala 108", "conteudo": "Quando chove, aparece uma goteira no teto da sala 108. Já colocamos balde mas está piorando.", "categoria": "Manutenção Predial", "urgencia": 4},
    {"titulo": "Pintura descascando no Bloco A", "conteudo": "A pintura externa do Bloco A está descascando em vários pontos. O prédio está com aparência deteriorada.", "categoria": "Manutenção Predial", "urgencia": 2},
    {"titulo": "Calçada quebrada na entrada", "conteudo": "A calçada na entrada principal está quebrada com um buraco. Risco de queda para pedestres.", "categoria": "Manutenção Predial", "urgencia": 4},
    {"titulo": "Forro de PVC caindo na sala 203", "conteudo": "O forro de PVC da sala 203 está cedendo e ameaça cair. Já removemos os alunos da área.", "categoria": "Manutenção Predial", "urgencia": 5},
    {"titulo": "Muro do estacionamento com trinca", "conteudo": "O muro lateral do estacionamento tem uma trinca grande. Parece estrutural.", "categoria": "Manutenção Predial", "urgencia": 3},

    {"titulo": "Grama alta na área esportiva", "conteudo": "A grama do campo de futebol e da área ao redor do ginásio está muito alta. Precisa de corte urgente.", "categoria": "Limpeza e Jardinagem", "urgencia": 2},
    {"titulo": "Árvore com galho prestes a cair", "conteudo": "Há uma árvore próxima ao estacionamento com um galho grande e seco, prestes a cair. Risco para os carros.", "categoria": "Limpeza e Jardinagem", "urgencia": 5},
    {"titulo": "Lixeiras transbordando na área externa", "conteudo": "As lixeiras da área externa entre os Blocos A e B estão transbordando. Mau cheiro e insetos.", "categoria": "Limpeza e Jardinagem", "urgencia": 4},
    {"titulo": "Mato crescendo na calçada", "conteudo": "Mato está crescendo nas frestas da calçada de acesso à biblioteca. Área está descuidada.", "categoria": "Limpeza e Jardinagem", "urgencia": 2},
    {"titulo": "Poda de árvores na entrada", "conteudo": "As árvores na entrada principal estão com galhos muito baixos, atrapalhando a passagem de veículos maiores.", "categoria": "Limpeza e Jardinagem", "urgencia": 3},

    {"titulo": "Funcionário da limpeza não compareceu", "conteudo": "O funcionário terceirizado responsável pela limpeza do Bloco C não compareceu hoje. Os banheiros estão sujos.", "categoria": "Suporte a Serviços Terceirizados", "urgencia": 4},
    {"titulo": "Vigilante reporta câmera com defeito", "conteudo": "O vigilante do turno noturno reportou que a câmera 3 (estacionamento) parou de funcionar.", "categoria": "Suporte a Serviços Terceirizados", "urgencia": 3},
    {"titulo": "Problema com empresa de jardinagem", "conteudo": "A empresa terceirizada de jardinagem não realizou o serviço programado para esta semana.", "categoria": "Suporte a Serviços Terceirizados", "urgencia": 2},
    {"titulo": "Reclamação sobre limpeza dos banheiros", "conteudo": "Alunos reclamam que os banheiros do Bloco B não estão sendo limpos adequadamente pela equipe terceirizada.", "categoria": "Suporte a Serviços Terceirizados", "urgencia": 3},
]

CHAMADOS_DUPLICADOS = [
    {
        "original": {"titulo": "Lâmpada queimada na sala 101 - Bloco A", "conteudo": "A lâmpada da sala 101 queimou novamente. Já foi solicitado reparo semana passada.", "categoria": "Elétrica"},
        "duplicata": {"titulo": "Luz da sala 101 não funciona", "conteudo": "A sala 101 está sem iluminação. A lâmpada não acende.", "categoria": "Elétrica"},
        "localizacao": "Bloco A - Salas de Aula",
        "dias_entre": 3,
    },
    {
        "original": {"titulo": "Vazamento no banheiro do Bloco C", "conteudo": "Torneira do banheiro masculino do Bloco C está vazando.", "categoria": "Hidráulica"},
        "duplicata": {"titulo": "Torneira pingando no banheiro masculino - administrativo", "conteudo": "No banheiro masculino do prédio administrativo, a torneira da pia da direita está pingando sem parar.", "categoria": "Hidráulica"},
        "localizacao": "Bloco C - Administrativo",
        "dias_entre": 5,
    },
    {
        "original": {"titulo": "Porta da sala 205 emperrada", "conteudo": "A porta da sala 205 no Bloco A não fecha direito. A dobradiça parece torta.", "categoria": "Carpintaria / Marcenaria"},
        "duplicata": {"titulo": "Problema na porta da sala 205", "conteudo": "Não consigo trancar a sala 205 após as aulas. A porta não encaixa no batente.", "categoria": "Carpintaria / Marcenaria"},
        "localizacao": "Bloco A - Salas de Aula",
        "dias_entre": 2,
    },
    {
        "original": {"titulo": "Goteira na biblioteca", "conteudo": "Quando chove aparece uma goteira no setor de periódicos da biblioteca.", "categoria": "Manutenção Predial"},
        "duplicata": {"titulo": "Infiltração no teto da biblioteca - setor de periódicos", "conteudo": "Está chovendo dentro da biblioteca na área dos periódicos. Livros sendo danificados.", "categoria": "Manutenção Predial"},
        "localizacao": "Biblioteca",
        "dias_entre": 7,
    },
    {
        "original": {"titulo": "Descarga não funciona - banheiro refeitório", "conteudo": "A descarga do banheiro próximo ao refeitório não está funcionando.", "categoria": "Hidráulica"},
        "duplicata": {"titulo": "Vaso sanitário sem descarga no refeitório", "conteudo": "O vaso sanitário do banheiro do refeitório está sem descarga. Situação anti-higiênica.", "categoria": "Hidráulica"},
        "localizacao": "Refeitório",
        "dias_entre": 1,
    },
    {
        "original": {"titulo": "Grama alta perto do ginásio", "conteudo": "A grama ao redor do ginásio está muito alta, dificultando o acesso.", "categoria": "Limpeza e Jardinagem"},
        "duplicata": {"titulo": "Mato alto na área do ginásio poliesportivo", "conteudo": "O mato cresceu muito na lateral do ginásio. Há risco de animais peçonhentos.", "categoria": "Limpeza e Jardinagem"},
        "localizacao": "Ginásio Poliesportivo",
        "dias_entre": 4,
    },
    {
        "original": {"titulo": "Tomada queimada no lab de informática", "conteudo": "Tomada da bancada 5 do laboratório de informática está queimada e com cheiro de queimado.", "categoria": "Elétrica"},
        "duplicata": {"titulo": "Problema elétrico na bancada do lab de informática", "conteudo": "A tomada da bancada 5 não funciona. Quando conectamos o computador, o disjuntor desarma.", "categoria": "Elétrica"},
        "localizacao": "Bloco B - Laboratórios",
        "dias_entre": 6,
    },
    {
        "original": {"titulo": "Cano vazando no alojamento feminino", "conteudo": "Há um vazamento no cano do banheiro do alojamento feminino, segundo andar.", "categoria": "Hidráulica"},
        "duplicata": {"titulo": "Vazamento no banheiro do alojamento", "conteudo": "Água vazando do cano no banheiro do segundo andar do alojamento. O chão está todo molhado.", "categoria": "Hidráulica"},
        "localizacao": "Alojamento Estudantil",
        "dias_entre": 2,
    },
]

CHAMADOS_OBRA = [
    {"titulo": "Construção de rampa de acessibilidade", "conteudo": "Solicito a construção de uma rampa de acessibilidade na entrada lateral do Bloco B. Atualmente não há acesso para cadeirantes.", "categoria": "Manutenção Predial", "urgencia": 4,
     "flag_obra": "OBRA - Construção nova de estrutura de acessibilidade, requer projeto e execução civil."},
    {"titulo": "Ampliação da sala de servidores", "conteudo": "O setor de TI precisa ampliar a sala de servidores. É necessário derrubar uma parede e expandir o espaço.", "categoria": "Manutenção Predial", "urgencia": 3,
     "flag_obra": "OBRA - Ampliação de espaço físico com demolição e construção."},
    {"titulo": "Construção de cobertura no estacionamento", "conteudo": "Solicito a construção de uma cobertura metálica no estacionamento dos servidores para proteger os veículos.", "categoria": "Mecânica Geral", "urgencia": 2,
     "flag_obra": "OBRA - Construção de nova estrutura metálica."},
    {"titulo": "Reforma completa dos banheiros do Bloco A", "conteudo": "Os banheiros do Bloco A precisam de reforma completa: troca de pisos, louças, instalações hidráulicas e elétricas.", "categoria": "Manutenção Predial", "urgencia": 3,
     "flag_obra": "OBRA - Reforma completa envolvendo múltiplas especialidades."},
    {"titulo": "Instalação de novo laboratório de química", "conteudo": "Precisamos adaptar a sala 401 para se tornar um laboratório de química, incluindo bancadas com pias, exaustão, instalação de gás e elétrica especial.", "categoria": "Manutenção Predial", "urgencia": 3,
     "flag_obra": "OBRA - Adaptação completa de espaço com múltiplas instalações novas."},
    {"titulo": "Construção de guarita nova", "conteudo": "A guarita atual é muito pequena e não comporta os equipamentos de monitoramento. Solicito construção de nova guarita.", "categoria": "Manutenção Predial", "urgencia": 2,
     "flag_obra": "OBRA - Construção de nova edificação."},
    {"titulo": "Pavimentação do acesso à fazenda escola", "conteudo": "A estrada de terra que conecta o campus à fazenda escola precisa ser pavimentada. Quando chove fica intransitável.", "categoria": "Manutenção Predial", "urgencia": 3,
     "flag_obra": "OBRA - Pavimentação de via, requer projeto de engenharia."},
]

CHAMADOS_CATEGORIA_ERRADA = [
    {"titulo": "Chuveiro elétrico queimou no alojamento", "conteudo": "O chuveiro do banheiro do alojamento masculino queimou. Não sai água quente.",
     "categoria_usada": "Hidráulica", "categoria_correta": "Elétrica", "urgencia": 3},
    {"titulo": "Fechadura eletrônica não funciona", "conteudo": "A fechadura eletrônica da porta do setor de TI parou de funcionar. Não conseguimos destrancar.",
     "categoria_usada": "Elétrica", "categoria_correta": "Mecânica Geral", "urgencia": 4},
    {"titulo": "Torneira do bebedouro caiu", "conteudo": "A torneirinha do bebedouro do Bloco A caiu e a água está jorrando.",
     "categoria_usada": "Mecânica Geral", "categoria_correta": "Hidráulica", "urgencia": 5},
    {"titulo": "Limpeza após obra no corredor", "conteudo": "Após o reparo na parede do corredor do Bloco C, ficou muito entulho e poeira. Precisa de limpeza.",
     "categoria_usada": "Manutenção Predial", "categoria_correta": "Limpeza e Jardinagem", "urgencia": 2},
    {"titulo": "Ventilador de teto fazendo barulho", "conteudo": "Ventilador de teto da sala 305 está com barulho forte, parece que as pás estão desbalanceadas.",
     "categoria_usada": "Elétrica", "categoria_correta": "Mecânica Geral", "urgencia": 3},
    {"titulo": "Porta de correr do almoxarifado", "conteudo": "A porta de correr de metal do almoxarifado está emperrada nos trilhos. Não abre.",
     "categoria_usada": "Carpintaria / Marcenaria", "categoria_correta": "Mecânica Geral", "urgencia": 3},
    {"titulo": "Jardim com mato invadindo calçada", "conteudo": "O mato do jardim lateral está invadindo a calçada e tampando o ralo de escoamento de água.",
     "categoria_usada": "Hidráulica", "categoria_correta": "Limpeza e Jardinagem", "urgencia": 2},
    {"titulo": "Cadeira de escritório quebrada", "conteudo": "A cadeira giratória do escritório da coordenação quebrou o pistão de gás. Não regula mais a altura.",
     "categoria_usada": "Carpintaria / Marcenaria", "categoria_correta": "Mecânica Geral", "urgencia": 2},
    {"titulo": "Ar-condicionado pingando água", "conteudo": "O ar-condicionado da sala da direção está pingando água dentro da sala. Formou uma poça no chão.",
     "categoria_usada": "Elétrica", "categoria_correta": "Hidráulica", "urgencia": 3},
    {"titulo": "Cerca da fazenda caiu", "conteudo": "A cerca de arame do pasto da fazenda escola caiu em um trecho de 20 metros. Os animais podem escapar.",
     "categoria_usada": "Manutenção Predial", "categoria_correta": "Mecânica Geral", "urgencia": 5},
]


CHAMADOS_CONTROLE_WORKFLOW = [
    {
        "tag": "DUPLICIDADE_PAR_A",
        "titulo": "[CTRL-WORKFLOW] Vazamento pia bloco C - registro A",
        "conteudo": "Vazamento persistente na pia do banheiro masculino do Bloco C, lado direito.",
        "categoria": "Hidráulica",
        "localizacao": "Bloco C - Administrativo",
        "status": 2,
        "tipo": 1,
        "urgencia": 3,
        "dias_atras": 4,
    },
    {
        "tag": "DUPLICIDADE_PAR_B",
        "titulo": "[CTRL-WORKFLOW] Torneira banheiro bloco C pingando - registro B",
        "conteudo": "Mesmo problema da pia do banheiro masculino do Bloco C, vazando continuamente.",
        "categoria": "Hidráulica",
        "localizacao": "Bloco C - Administrativo",
        "status": 2,
        "tipo": 1,
        "urgencia": 4,
        "dias_atras": 1,
    },
    {
        "tag": "NAO_DUPLICADO",
        "titulo": "[CTRL-WORKFLOW] Lampada queimada sala 204 bloco A",
        "conteudo": "Lampada da sala 204 nao acende. Problema local e pontual.",
        "categoria": "Elétrica",
        "localizacao": "Bloco A - Salas de Aula",
        "status": 2,
        "tipo": 1,
        "urgencia": 3,
        "dias_atras": 2,
    },
    {
        "tag": "OBRA_DDI_DG",
        "titulo": "[CTRL-WORKFLOW] Construcao de nova sala de apoio no bloco B",
        "conteudo": "Necessaria construcao de novo espaco com alvenaria e instalacoes completas. [METADATA_TESTE: CENARIO_CONTROLE=OBRA_DDI_DG]",
        "categoria": "Manutenção Predial",
        "localizacao": "Bloco B - Laboratórios",
        "status": 2,
        "tipo": 2,
        "urgencia": 4,
        "dias_atras": 3,
    },
    {
        "tag": "MANUTENCAO_DEMO",
        "titulo": "[CTRL-WORKFLOW] Troca de tomada bancada 2 laboratorio",
        "conteudo": "Tomada queimada na bancada 2 do laboratorio. Servico eletrico predial simples. [METADATA_TESTE: CENARIO_CONTROLE=MANUTENCAO_DEMO]",
        "categoria": "Elétrica",
        "localizacao": "Bloco B - Laboratórios",
        "status": 2,
        "tipo": 1,
        "urgencia": 3,
        "dias_atras": 2,
    },
    {
        "tag": "MANUTENCAO_SOB_DEMANDA",
        "titulo": "[CTRL-WORKFLOW] Split ar-condicionado laboratorio TI",
        "conteudo": "Ar-condicionado split do laboratorio de TI nao refrigera e pinga agua. [METADATA_TESTE: CENARIO_CONTROLE=MANUTENCAO_SOB_DEMANDA]",
        "categoria": "Mecânica Geral",
        "localizacao": "Setor de TI",
        "status": 2,
        "tipo": 1,
        "urgencia": 4,
        "dias_atras": 2,
    },
    {
        "tag": "PENDENTE_STATUS_4",
        "titulo": "[CTRL-WORKFLOW] Pendente aguardando material para reparo",
        "conteudo": "Chamado em pendencia por aguardo de material eletrico para conclusao do reparo.",
        "categoria": "Elétrica",
        "localizacao": "Prefeitura do Campus",
        "status": 4,
        "tipo": 1,
        "urgencia": 2,
        "dias_atras": 40,
    },
    {
        "tag": "PLANEJADO_STATUS_3",
        "titulo": "[CTRL-WORKFLOW] Planejamento de intervencao hidraulica",
        "conteudo": "Chamado requer planejamento tecnico antes da execucao por impacto em area de circulacao.",
        "categoria": "Hidráulica",
        "localizacao": "Refeitório",
        "status": 3,
        "tipo": 1,
        "urgencia": 3,
        "dias_atras": 20,
    },
    {
        "tag": "FINALIZADO_STATUS_5",
        "titulo": "[CTRL-WORKFLOW] Finalizado recente para teste de duplicidade",
        "conteudo": "Chamado finalizado recentemente para validar comparacao com novos chamados semelhantes.",
        "categoria": "Carpintaria / Marcenaria",
        "localizacao": "Auditório",
        "status": 5,
        "tipo": 1,
        "urgencia": 2,
        "dias_atras": 10,
    },
    {
        "tag": "CATEGORIA_ERRADA_CONTROLADA",
        "titulo": "[CTRL-WORKFLOW] Chuveiro queimado alojamento (categoria propositalmente errada)",
        "conteudo": "Problema eletrico no chuveiro, mas classificado propositalmente como Hidraulica. [METADATA_TESTE: CENARIO_CONTROLE=CATEGORIA_ERRADA]",
        "categoria": "Hidráulica",
        "localizacao": "Alojamento Estudantil",
        "status": 2,
        "tipo": 1,
        "urgencia": 3,
        "dias_atras": 1,
    },
]

CONTROLE_EXPECTATIVAS = {
    "DUPLICIDADE_PAR_A": {
        "duplicado_esperado": False,
        "classificacao_esperada": "DEMO",
        "executor_esperado": "DEMO",
        "nivel_dificuldade": "MEDIO",
    },
    "DUPLICIDADE_PAR_B": {
        "duplicado_esperado": True,
        "referencia_tag": "DUPLICIDADE_PAR_A",
        "classificacao_esperada": "DUPLICADO",
        "nivel_dificuldade": "MEDIO",
    },
    "NAO_DUPLICADO": {
        "duplicado_esperado": False,
        "classificacao_esperada": "DEMO",
        "executor_esperado": "DEMO",
        "nivel_dificuldade": "FACIL",
    },
    "OBRA_DDI_DG": {
        "duplicado_esperado": False,
        "classificacao_esperada": "OBRA",
        "executor_esperado": "DDI_DG",
        "status_final_esperado": "Fechado",
        "nivel_dificuldade": "FACIL",
    },
    "MANUTENCAO_DEMO": {
        "duplicado_esperado": False,
        "classificacao_esperada": "DEMO",
        "executor_esperado": "DEMO",
        "nivel_dificuldade": "FACIL",
    },
    "MANUTENCAO_SOB_DEMANDA": {
        "duplicado_esperado": False,
        "classificacao_esperada": "SOB_DEMANDA",
        "executor_esperado": "SOB_DEMANDA",
        "status_final_esperado": "Planejado",
        "nivel_dificuldade": "MEDIO",
    },
    "PENDENTE_STATUS_4": {
        "duplicado_esperado": False,
        "status_final_esperado": "Pendente",
        "nivel_dificuldade": "FACIL",
    },
    "PLANEJADO_STATUS_3": {
        "duplicado_esperado": False,
        "status_final_esperado": "Planejado",
        "nivel_dificuldade": "FACIL",
    },
    "FINALIZADO_STATUS_5": {
        "duplicado_esperado": False,
        "status_final_esperado": "Solucionado",
        "nivel_dificuldade": "FACIL",
    },
    "CATEGORIA_ERRADA_CONTROLADA": {
        "duplicado_esperado": False,
        "classificacao_esperada": "DEMO",
        "executor_esperado": "DEMO",
        "nivel_dificuldade": "DIFICIL",
    },
}

DATASET_CONTROLE_ROWS = []



class GLPIClient:
    """Cliente para interagir com a API REST do GLPI."""

    def __init__(self, url: str, app_token: str, user: str, password: str):
        self.base_url = url.rstrip("/") + "/apirest.php"
        self.app_token = app_token
        self.session_token = None
        self.user = user
        self.password = password

    def init_session(self):
        """Inicia sessão na API do GLPI."""
        headers = {
            "App-Token": self.app_token,
            "Authorization": f"Basic {self._encode_credentials()}",
        }
        resp = requests.get(f"{self.base_url}/initSession", headers=headers)
        if resp.status_code != 200:
            print(f"[ERRO] Falha ao iniciar sessão: {resp.status_code}")
            print(f"  Resposta: {resp.text}")
            print(f"\n  Verifique se:")
            print(f"    1. O GLPI está rodando em {self.base_url.replace('/apirest.php', '')}")
            print(f"    2. A API REST está habilitada (Configurar > Geral > API)")
            print(f"    3. O App-Token está correto")
            print(f"    4. Login com credenciais está habilitado na API")
            sys.exit(1)
        data = resp.json()
        self.session_token = data.get("session_token")
        print(f"[OK] Sessão iniciada com sucesso.")
        return self.session_token

    def kill_session(self):
        """Encerra a sessão na API."""
        if self.session_token:
            try:
                requests.get(f"{self.base_url}/killSession", headers=self._headers())
                print("[OK] Sessão encerrada.")
            except Exception:
                pass

    def _encode_credentials(self) -> str:
        import base64
        return base64.b64encode(f"{self.user}:{self.password}".encode()).decode()

    def _headers(self) -> dict:
        return {
            "App-Token": self.app_token,
            "Session-Token": self.session_token,
            "Content-Type": "application/json",
        }

    def create_item(self, itemtype: str, data: dict) -> dict | None:
        """Cria um item no GLPI via API."""
        resp = requests.post(
            f"{self.base_url}/{itemtype}",
            headers=self._headers(),
            json={"input": data},
        )
        if resp.status_code in (200, 201):
            result = resp.json()
            if isinstance(result, list):
                return result[0] if result else None
            return result
        else:
            print(f"  [AVISO] Falha ao criar {itemtype}: {resp.status_code} - {resp.text}")
            return None

    def search_items(self, itemtype: str, criteria: list = None, range_str: str = "0-100") -> list:
        """Busca itens no GLPI."""
        params = {"range": range_str}
        if criteria:
            for i, c in enumerate(criteria):
                for k, v in c.items():
                    params[f"criteria[{i}][{k}]"] = v
        resp = requests.get(
            f"{self.base_url}/search/{itemtype}",
            headers=self._headers(),
            params=params,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            return data if isinstance(data, list) else []
        return []

    def get_items(self, itemtype: str, range_str: str = "0-200") -> list:
        """Lista itens do GLPI."""
        params = {"range": range_str}
        resp = requests.get(
            f"{self.base_url}/{itemtype}",
            headers=self._headers(),
            params=params,
        )
        if resp.status_code == 200:
            return resp.json()
        return []

    def get_item(self, itemtype: str, item_id: int) -> dict:
        """Obtém um item específico."""
        resp = requests.get(
            f"{self.base_url}/{itemtype}/{item_id}",
            headers=self._headers(),
        )
        if resp.status_code == 200:
            return resp.json()
        return {}



def seed_categorias(client: GLPIClient) -> dict:
    """Cria as categorias ITIL e retorna mapeamento nome -> id."""
    print("\n=== Criando Categorias ITIL ===")
    cat_map = {}

    # Primeiro, verificar se já existem categorias
    existentes = client.get_items("ITILCategory")
    for cat in existentes:
        if isinstance(cat, dict) and "name" in cat:
            cat_map[cat["name"]] = cat["id"]

    for cat in CATEGORIAS:
        if cat["name"] in cat_map:
            print(f"  [SKIP] Categoria já existe: {cat['name']}")
            continue
        result = client.create_item("ITILCategory", {
            "name": cat["name"],
            "comment": cat["comment"],
            "is_incident": 1,
            "is_request": 1,
        })
        if result and "id" in result:
            cat_map[cat["name"]] = result["id"]
            print(f"  [OK] Categoria criada: {cat['name']} (ID: {result['id']})")
        else:
            print(f"  [ERRO] Não criou: {cat['name']}")

    return cat_map


def seed_localizacoes(client: GLPIClient) -> dict:
    """Cria as localizações e retorna mapeamento nome -> id."""
    print("\n=== Criando Localizações (Setores) ===")
    loc_map = {}

    existentes = client.get_items("Location")
    for loc in existentes:
        if isinstance(loc, dict) and "name" in loc:
            loc_map[loc["name"]] = loc["id"]

    for loc in LOCALIZACOES:
        if loc["name"] in loc_map:
            print(f"  [SKIP] Local já existe: {loc['name']}")
            continue
        result = client.create_item("Location", {
            "name": loc["name"],
            "comment": loc.get("comment", ""),
        })
        if result and "id" in result:
            loc_map[loc["name"]] = result["id"]
            print(f"  [OK] Local criado: {loc['name']} (ID: {result['id']})")
        else:
            print(f"  [ERRO] Não criou: {loc['name']}")

    return loc_map


def ensure_user_email(client: GLPIClient, user_id: int, email: str) -> None:
    """Garante um e-mail padrão para o usuário solicitante de teste."""
    if not user_id or not email:
        return

    existentes = client.get_items(f"User/{user_id}/UserEmail")
    for item in existentes:
        if isinstance(item, dict) and str(item.get("email", "")).lower() == email.lower():
            return

    result = client.create_item(
        "UserEmail",
        {"users_id": user_id, "email": email, "is_default": 1},
    )
    if result and "id" in result:
        print(f"  [OK] E-mail do usuário #{user_id}: {email}")
    else:
        print(f"  [AVISO] Não foi possível criar e-mail para usuário #{user_id}: {email}")


def seed_usuarios(client: GLPIClient) -> list:
    """Cria usuários solicitantes e retorna lista de IDs."""
    print("\n=== Criando Usuários Solicitantes ===")
    user_ids = []
    user_id_by_name = {}

    existentes = client.get_items("User")
    nomes_existentes = set()
    for u in existentes:
        if isinstance(u, dict) and "name" in u:
            nomes_existentes.add(u["name"])
            # Se é um de nossos usuários, guardar o ID
            for usuario in USUARIOS:
                if u["name"] == usuario["name"]:
                    user_ids.append(u["id"])
                    user_id_by_name[usuario["name"]] = u["id"]

    for usuario in USUARIOS:
        if usuario["name"] in nomes_existentes:
            print(f"  [SKIP] Usuário já existe: {usuario['name']}")
            continue
        result = client.create_item("User", {
            "name": usuario["name"],
            "realname": usuario["realname"],
            "firstname": usuario["firstname"],
            "phone": usuario.get("phone", ""),
            "password": "Teste@1234",
            "password2": "Teste@1234",
        })
        if result and "id" in result:
            user_ids.append(result["id"])
            user_id_by_name[usuario["name"]] = result["id"]
            print(f"  [OK] Usuário criado: {usuario['firstname']} {usuario['realname']} (ID: {result['id']})")
        else:
            print(f"  [ERRO] Não criou: {usuario['name']}")

    for usuario in USUARIOS:
        user_id = user_id_by_name.get(usuario["name"])
        ensure_user_email(client, user_id, f"{usuario['name']}@campus.local")

    # Se nenhum usuário foi criado/encontrado, usar user ID 2 (glpi padrão)
    if not user_ids:
        user_ids = [2]
    return user_ids


def gerar_data_aleatoria(semanas_atras: int = 6) -> str:
    """Gera uma data aleatória dentro das últimas N semanas."""
    agora = datetime.now()
    inicio = agora - timedelta(weeks=semanas_atras)
    delta = agora - inicio
    dias_aleatorio = random.randint(0, delta.days)
    hora = random.randint(7, 18)
    minuto = random.randint(0, 59)
    data = inicio + timedelta(days=dias_aleatorio, hours=hora, minutes=minuto)
    return data.strftime("%Y-%m-%d %H:%M:%S")


def status_aleatorio() -> int:
    """Retorna um status aleatório com distribuição realista."""
    # 2=atribuído, 3=planejado, 4=pendente, 5=solucionado
    # No ambiente real da prefeitura, o fluxo operacional usa majoritariamente 2/3/4/5.
    return random.choices(
        [2, 3, 4, 5],
        weights=[45, 10, 30, 15],
        k=1
    )[0]


def seed_chamados_normais(client: GLPIClient, cat_map: dict, loc_map: dict, user_ids: list) -> int:
    """Cria chamados normais de manutenção."""
    print("\n=== Criando Chamados Normais ===")
    count = 0
    loc_names = list(loc_map.keys())

    for chamado in CHAMADOS_NORMAIS:
        cat_id = cat_map.get(chamado["categoria"])
        if not cat_id:
            print(f"  [AVISO] Categoria não encontrada: {chamado['categoria']}")
            continue

        loc_name = random.choice(loc_names)
        loc_id = loc_map[loc_name]
        user_id = random.choice(user_ids)
        data = gerar_data_aleatoria()
        status = status_aleatorio()

        result = client.create_item("Ticket", {
            "name": chamado["titulo"],
            "content": chamado["conteudo"],
            "itilcategories_id": cat_id,
            "locations_id": loc_id,
            "type": 1,  # incidente
            "status": status,
            "urgency": chamado.get("urgencia", 3),
            "impact": random.randint(2, 4),
            "_users_id_requester": user_id,
            "date": data,
        })
        if result and "id" in result:
            count += 1
            print(f"  [OK] #{result['id']} - {chamado['titulo'][:50]}...")
        else:
            print(f"  [ERRO] Falha: {chamado['titulo'][:50]}...")

    return count


def seed_chamados_duplicados(client: GLPIClient, cat_map: dict, loc_map: dict, user_ids: list) -> int:
    """Cria pares de chamados duplicados (mesmo setor + serviço)."""
    print("\n=== Criando Chamados Duplicados (pares) ===")
    count = 0

    for par in CHAMADOS_DUPLICADOS:
        cat_id = cat_map.get(par["original"]["categoria"])
        loc_id = loc_map.get(par["localizacao"])
        if not cat_id or not loc_id:
            continue

        # Data do original
        agora = datetime.now()
        data_original = agora - timedelta(weeks=random.randint(1, 4), days=random.randint(0, 6))
        data_duplicata = data_original + timedelta(days=par["dias_entre"])

        user_id_1 = random.choice(user_ids)
        user_id_2 = random.choice(user_ids)

        # Criar original
        r1 = client.create_item("Ticket", {
            "name": par["original"]["titulo"],
            "content": par["original"]["conteudo"],
            "itilcategories_id": cat_id,
            "locations_id": loc_id,
            "type": 1,
            "status": random.choice([1, 2, 3, 4]),  # ainda aberto
            "urgency": random.randint(3, 4),
            "impact": 3,
            "_users_id_requester": user_id_1,
            "date": data_original.strftime("%Y-%m-%d %H:%M:%S"),
        })
        if r1 and "id" in r1:
            count += 1
            print(f"  [OK] ORIGINAL #{r1['id']} - {par['original']['titulo'][:50]}...")

        # Criar duplicata
        r2 = client.create_item("Ticket", {
            "name": par["duplicata"]["titulo"],
            "content": par["duplicata"]["conteudo"],
            "itilcategories_id": cat_id,
            "locations_id": loc_id,
            "type": 1,
            "status": 2,  # processando atribuido
            "urgency": random.randint(3, 5),
            "impact": 3,
            "_users_id_requester": user_id_2,
            "date": data_duplicata.strftime("%Y-%m-%d %H:%M:%S"),
        })
        if r2 and "id" in r2:
            count += 1
            print(f"  [OK] DUPLICATA #{r2['id']} - {par['duplicata']['titulo'][:50]}...")

    return count


def seed_chamados_obra(client: GLPIClient, cat_map: dict, loc_map: dict, user_ids: list) -> int:
    """Cria chamados que na verdade são OBRA (não manutenção)."""
    print("\n=== Criando Chamados de Obra (classificados erroneamente como manutenção) ===")
    count = 0
    loc_names = list(loc_map.keys())

    for chamado in CHAMADOS_OBRA:
        cat_id = cat_map.get(chamado["categoria"])
        if not cat_id:
            continue

        loc_name = random.choice(loc_names)
        loc_id = loc_map[loc_name]
        user_id = random.choice(user_ids)
        data = gerar_data_aleatoria(semanas_atras=4)

        # Adicionar flag de obra no conteúdo (para validação posterior)
        conteudo = chamado["conteudo"] + f"\n\n[METADATA_TESTE: {chamado['flag_obra']}]"

        result = client.create_item("Ticket", {
            "name": chamado["titulo"],
            "content": conteudo,
            "itilcategories_id": cat_id,
            "locations_id": loc_id,
            "type": 2,  # requisição
            "status": 2,  # processando atribuido
            "urgency": chamado.get("urgencia", 3),
            "impact": 3,
            "_users_id_requester": user_id,
            "date": data,
        })
        if result and "id" in result:
            count += 1
            print(f"  [OK] OBRA #{result['id']} - {chamado['titulo'][:50]}...")
        else:
            print(f"  [ERRO] Falha: {chamado['titulo'][:50]}...")

    return count


def seed_chamados_categoria_errada(client: GLPIClient, cat_map: dict, loc_map: dict, user_ids: list) -> int:
    """Cria chamados com categoria possivelmente errada."""
    print("\n=== Criando Chamados com Categoria Possivelmente Errada ===")
    count = 0
    loc_names = list(loc_map.keys())

    for chamado in CHAMADOS_CATEGORIA_ERRADA:
        # Usa a categoria ERRADA (como o usuário classificaria erroneamente)
        cat_id = cat_map.get(chamado["categoria_usada"])
        if not cat_id:
            continue

        loc_name = random.choice(loc_names)
        loc_id = loc_map[loc_name]
        user_id = random.choice(user_ids)
        data = gerar_data_aleatoria()

        # Adicionar metadata para validação
        conteudo = chamado["conteudo"] + f"\n\n[METADATA_TESTE: Categoria usada='{chamado['categoria_usada']}', Categoria correta='{chamado['categoria_correta']}']"

        result = client.create_item("Ticket", {
            "name": chamado["titulo"],
            "content": conteudo,
            "itilcategories_id": cat_id,
            "locations_id": loc_id,
            "type": 1,
            "status": status_aleatorio(),
            "urgency": chamado.get("urgencia", 3),
            "impact": random.randint(2, 4),
            "_users_id_requester": user_id,
            "date": data,
        })
        if result and "id" in result:
            count += 1
            print(f"  [OK] CAT_ERRADA #{result['id']} - {chamado['titulo'][:50]}...")
        else:
            print(f"  [ERRO] Falha: {chamado['titulo'][:50]}...")

    return count


def sql_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def dataset_controle_insert_sql(rows: list[dict]) -> str:
    if not rows:
        return "-- Nenhum registro de dataset_controle gerado.\n"

    statements = [
        "CREATE TABLE IF NOT EXISTS dataset_controle (",
        "  id BIGSERIAL PRIMARY KEY,",
        "  ticket_id BIGINT,",
        "  origem TEXT NOT NULL DEFAULT 'SEED_CONTROLADO',",
        "  cenario_controle TEXT,",
        "  duplicado_esperado BOOLEAN,",
        "  referencia_duplicado_esperada BIGINT,",
        "  classificacao_esperada TEXT,",
        "  executor_esperado TEXT,",
        "  status_final_esperado TEXT,",
        "  nivel_dificuldade TEXT,",
        "  observacao TEXT,",
        "  criado_em TIMESTAMPTZ DEFAULT NOW()",
        ");",
    ]
    for row in rows:
        values = [
            sql_literal(row.get("ticket_id")),
            sql_literal(row.get("origem", "SEED_CONTROLADO")),
            sql_literal(row.get("cenario_controle")),
            sql_literal(row.get("duplicado_esperado")),
            sql_literal(row.get("referencia_duplicado_esperada")),
            sql_literal(row.get("classificacao_esperada")),
            sql_literal(row.get("executor_esperado")),
            sql_literal(row.get("status_final_esperado")),
            sql_literal(row.get("nivel_dificuldade")),
            sql_literal(row.get("observacao")),
        ]
        statements.append(
            "INSERT INTO dataset_controle("
            "ticket_id, origem, cenario_controle, duplicado_esperado, referencia_duplicado_esperada, "
            "classificacao_esperada, executor_esperado, status_final_esperado, nivel_dificuldade, observacao"
            ") SELECT "
            + ", ".join(values)
            + " WHERE NOT EXISTS ("
            + "SELECT 1 FROM dataset_controle WHERE ticket_id="
            + sql_literal(row.get("ticket_id"))
            + " AND origem="
            + sql_literal(row.get("origem", "SEED_CONTROLADO"))
            + ");"
        )
    return "\n".join(statements) + "\n"


def registrar_dataset_controle(rows: list[dict], args) -> None:
    if not rows:
        return

    sql = dataset_controle_insert_sql(rows)
    if args.dataset_controle_sql:
        path = Path(args.dataset_controle_sql)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql, encoding="utf-8", newline="\n")
        print(f"  [OK] SQL dataset_controle salvo em: {path}")

    if args.registrar_dataset_controle:
        docker_context = os.getenv("DOCKER_CONTEXT", "desktop-linux")
        os.environ["DOCKER_CONTEXT"] = docker_context
        cmd = [
            "docker",
            "--context",
            docker_context,
            "exec",
            "-i",
            args.postgres_container,
            "psql",
            "-U",
            args.postgres_user,
            "-d",
            args.postgres_db,
        ]
        result = subprocess.run(cmd, input=sql, text=True, capture_output=True, check=False)
        if result.returncode == 0:
            print(f"  [OK] dataset_controle registrado no PostgreSQL ({len(rows)} linhas esperadas).")
        else:
            print("  [ERRO] Falha ao registrar dataset_controle no PostgreSQL.")
            if result.stderr:
                print(result.stderr.strip())


def seed_chamados_controle_workflow(client: GLPIClient, cat_map: dict, loc_map: dict, user_ids: list) -> int:
    """Cria lote controlado e rastreavel para validar cada branch do workflow."""
    print("\n=== Criando Chamados CONTROLADOS do Workflow ===")
    count = 0
    created_by_tag = {}

    existentes = client.search_items(
        "Ticket",
        criteria=[{"field": 1, "searchtype": "contains", "value": "[CTRL-WORKFLOW]"}],
        range_str="0-999",
    )
    titulos_existentes = set()
    for item in existentes:
        if isinstance(item, dict):
            titulo = item.get("1") or item.get("name")
            if titulo:
                titulos_existentes.add(titulo)

    for chamado in CHAMADOS_CONTROLE_WORKFLOW:
        titulo = chamado["titulo"]
        if titulo in titulos_existentes:
            print(f"  [SKIP] Controle já existe: {titulo}")
            continue

        cat_id = cat_map.get(chamado["categoria"])
        loc_id = loc_map.get(chamado["localizacao"])
        if not cat_id or not loc_id:
            print(f"  [AVISO] Categoria/localizacao nao encontrados para: {titulo}")
            continue

        user_id = random.choice(user_ids)
        data = (datetime.now() - timedelta(days=chamado.get("dias_atras", 1))).strftime("%Y-%m-%d %H:%M:%S")
        conteudo = chamado["conteudo"] + f"\n\n[METADATA_TESTE: CENARIO_CONTROLE={chamado['tag']}]"

        result = client.create_item(
            "Ticket",
            {
                "name": titulo,
                "content": conteudo,
                "itilcategories_id": cat_id,
                "locations_id": loc_id,
                "type": chamado.get("tipo", 1),
                "status": chamado.get("status", 2),
                "urgency": chamado.get("urgencia", 3),
                "impact": 3,
                "_users_id_requester": user_id,
                "date": data,
            },
        )
        if result and "id" in result:
            count += 1
            ticket_id = int(result["id"])
            created_by_tag[chamado["tag"]] = ticket_id
            esperado = dict(CONTROLE_EXPECTATIVAS.get(chamado["tag"], {}))
            referencia_tag = esperado.pop("referencia_tag", None)
            referencia_id = created_by_tag.get(referencia_tag) if referencia_tag else None
            DATASET_CONTROLE_ROWS.append(
                {
                    "ticket_id": ticket_id,
                    "origem": "SEED_CONTROLADO",
                    "cenario_controle": chamado["tag"],
                    "referencia_duplicado_esperada": referencia_id,
                    "observacao": f"Gerado por seed_glpi.py --seed-controle; titulo={titulo}",
                    **esperado,
                }
            )
            print(f"  [OK] CTRL #{result['id']} - {titulo}")
        else:
            print(f"  [ERRO] Falha ao criar controle: {titulo}")

    return count



def main():
    parser = argparse.ArgumentParser(
        description="Seed GLPI com dados realistas do Campus Rio Pomba",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplo de uso:
  python seed_glpi.py --url http://localhost:9080 --app-token abc123def456 --user usuario --password senha

Pré-requisitos:
  1. GLPI rodando e acessível
  2. API REST habilitada (Configurar > Geral > API)
  3. App-Token gerado (Configurar > Geral > API > clientes API)
  4. Login com credenciais habilitado na configuração da API
        """,
    )
    parser.add_argument("--url", default=GLPI_DEFAULT_URL, help=f"URL do GLPI (padrão: {GLPI_DEFAULT_URL})")
    parser.add_argument(
        "--app-token",
        default=os.getenv("GLPI_APP_TOKEN", ""),
        help="App-Token da API do GLPI (ou GLPI_APP_TOKEN)",
    )
    parser.add_argument(
        "--user",
        default=GLPI_DEFAULT_USER,
        help="Usuário GLPI (ou GLPI_USER)",
    )
    parser.add_argument(
        "--password",
        default=GLPI_DEFAULT_PASS,
        help="Senha GLPI (ou GLPI_PASSWORD)",
    )
    parser.add_argument("--skip-normais", action="store_true", help="Pular chamados normais")
    parser.add_argument("--skip-duplicados", action="store_true", help="Pular chamados duplicados")
    parser.add_argument("--skip-obras", action="store_true", help="Pular chamados de obra")
    parser.add_argument("--skip-errados", action="store_true", help="Pular chamados com categoria errada")
    parser.add_argument("--seed-controle", action="store_true", help="Criar lote controlado para validar branches do workflow")
    parser.add_argument("--somente-controle", action="store_true", help="Criar apenas lote controlado (sem lotes padrao)")
    parser.add_argument("--dataset-controle-sql", default="", help="Salvar SQL gerado para popular dataset_controle")
    parser.add_argument("--registrar-dataset-controle", action="store_true", help="Executar SQL do dataset_controle no PostgreSQL via Docker")
    parser.add_argument("--nao-registrar-dataset-controle", action="store_true", help="Criar controle no GLPI sem tentar registrar dataset_controle")
    parser.add_argument("--postgres-container", default="glpi-dedup-db", help="Container PostgreSQL do workflow")
    parser.add_argument("--postgres-user", default="triagem_user", help="Usuário PostgreSQL")
    parser.add_argument("--postgres-db", default="triagem", help="Banco PostgreSQL")

    args = parser.parse_args()
    if not args.app_token or args.app_token.upper() == "CHANGE_ME":
        parser.error("informe --app-token ou GLPI_APP_TOKEN")
    if not args.user or args.user.upper() == "CHANGE_ME":
        parser.error("informe --user ou GLPI_USER")
    if not args.password or args.password.upper() == "CHANGE_ME":
        parser.error("informe --password ou GLPI_PASSWORD")

    print("=" * 60)
    print("  GLPI Seeder - Campus Rio Pomba")
    print("  Dados de teste para automação de chamados")
    print("=" * 60)
    print(f"\n  URL: {args.url}")
    print(f"  Usuário: {args.user}")

    # Iniciar sessão
    client = GLPIClient(args.url, args.app_token, args.user, args.password)
    client.init_session()

    try:
        cat_map = seed_categorias(client)
        if not cat_map:
            print("\n[ERRO] Nenhuma categoria criada. Verifique a API.")
            return

        loc_map = seed_localizacoes(client)
        if not loc_map:
            print("\n[ERRO] Nenhuma localização criada.")
            return

        user_ids = seed_usuarios(client)

        total = 0

        if not args.somente_controle and not args.skip_normais:
            total += seed_chamados_normais(client, cat_map, loc_map, user_ids)

        if not args.somente_controle and not args.skip_duplicados:
            total += seed_chamados_duplicados(client, cat_map, loc_map, user_ids)

        if not args.somente_controle and not args.skip_obras:
            total += seed_chamados_obra(client, cat_map, loc_map, user_ids)

        if not args.somente_controle and not args.skip_errados:
            total += seed_chamados_categoria_errada(client, cat_map, loc_map, user_ids)

        if args.seed_controle or args.somente_controle:
            total += seed_chamados_controle_workflow(client, cat_map, loc_map, user_ids)
            if not args.nao_registrar_dataset_controle:
                args.registrar_dataset_controle = True
            registrar_dataset_controle(DATASET_CONTROLE_ROWS, args)

        print("\n" + "=" * 60)
        print(f"  SEED CONCLUÍDO!")
        print(f"  Categorias: {len(cat_map)}")
        print(f"  Localizações: {len(loc_map)}")
        print(f"  Usuários: {len(user_ids)}")
        print(f"  Chamados criados: {total}")
        print("=" * 60)
        print(f"\n  Tipos de chamados criados:")
        if not args.somente_controle and not args.skip_normais:
            print(f"    - Normais (manutenção): {len(CHAMADOS_NORMAIS)}")
        if not args.somente_controle and not args.skip_duplicados:
            print(f"    - Duplicados (pares): {len(CHAMADOS_DUPLICADOS)} pares = {len(CHAMADOS_DUPLICADOS)*2} chamados")
        if not args.somente_controle and not args.skip_obras:
            print(f"    - Obra (não manutenção): {len(CHAMADOS_OBRA)}")
        if not args.somente_controle and not args.skip_errados:
            print(f"    - Categoria errada: {len(CHAMADOS_CATEGORIA_ERRADA)}")
        if args.seed_controle or args.somente_controle:
            print(f"    - Controle de branches do workflow: {len(CHAMADOS_CONTROLE_WORKFLOW)}")
        print(f"\n  Acesse o GLPI em: {args.url}")
        print(f"  Login: {args.user} (senha não exibida)")

    finally:
        client.kill_session()


if __name__ == "__main__":
    main()
