import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

def create_principia_article():
    doc = Document()
    
    # Configuração de Página A4 e Margens segundo Revista Principia:
    # Superior = 3,5 cm; Inferior = 2,0 cm; Esquerda = 2,5 cm; Direita = 2,5 cm
    for section in doc.sections:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(3.5)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)
    
    # Estilo base
    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Times New Roman'
    normal_style.font.size = Pt(11)
    normal_style.font.color.rgb = RGBColor(0, 0, 0)
    normal_style.paragraph_format.line_spacing = 1.0
    normal_style.paragraph_format.space_before = Pt(0)
    normal_style.paragraph_format.space_after = Pt(0)
    
    def add_p(text="", align=WD_ALIGN_PARAGRAPH.JUSTIFY, bold=False, italic=False, size=11, first_line_indent=1.0, space_after=0, space_before=0):
        p = doc.add_paragraph()
        p.alignment = align
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_before = Pt(space_before)
        p.paragraph_format.space_after = Pt(space_after)
        if first_line_indent > 0:
            p.paragraph_format.first_line_indent = Cm(first_line_indent)
        else:
            p.paragraph_format.first_line_indent = Cm(0)
        
        if text:
            run = p.add_run(text)
            run.font.name = 'Times New Roman'
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.italic = italic
        return p

    def add_sec_title(title):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.first_line_indent = Cm(0)
        run = p.add_run(title)
        run.font.name = 'Times New Roman'
        run.font.size = Pt(11)
        run.font.bold = True
        return p

    def add_subsec_title(title):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.first_line_indent = Cm(0)
        run = p.add_run(title)
        run.font.name = 'Times New Roman'
        run.font.size = Pt(11)
        run.font.bold = True
        return p

    # --- Título em Português ---
    # Tamanho 12, Negrito, Centralizado, sem ponto final, máx 50 palavras, apenas inicial maiúscula
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title.paragraph_format.line_spacing = 1.0
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(18)
    p_title.paragraph_format.first_line_indent = Cm(0)
    run_title = p_title.add_run("Automação orientada a eventos e inteligência artificial híbrida na gestão de chamados públicos: implementação e avaliação do estado futuro de manutenção predial")
    run_title.font.name = 'Times New Roman'
    run_title.font.size = Pt(12)
    run_title.font.bold = True

    # --- Resumo em Português ---
    # Entre 200 e 300 palavras, Times 11, parágrafo único, justificado, sem recuo
    p_res_title = doc.add_paragraph()
    p_res_title.paragraph_format.line_spacing = 1.0
    p_res_title.paragraph_format.space_before = Pt(6)
    p_res_title.paragraph_format.space_after = Pt(4)
    p_res_title.paragraph_format.first_line_indent = Cm(0)
    run_res_title = p_res_title.add_run("Resumo")
    run_res_title.font.name = 'Times New Roman'
    run_res_title.font.size = Pt(11)
    run_res_title.font.bold = True

    resumo_texto = (
        "A modernização da gestão pública demanda a evolução de modelos conceituais para sistemas operacionais capazes de "
        "mitigar gargalos reais de atendimento. A partir da modelagem dos processos de manutenção e infraestrutura física da "
        "Prefeitura de Campus do Instituto Federal do Sudeste de Minas Gerais, este estudo teve como objetivo projetar, "
        "implementar e avaliar uma arquitetura automatizada orientada a eventos para o estado futuro (TO-BE), integrando o "
        "sistema de chamados GLPI, orquestração assíncrona com n8n e inteligência artificial híbrida sob governança humana contínua. "
        "A pesquisa é aplicada e descritiva, conduzida como estudo de caso de engenharia de software e processos. A arquitetura "
        "foi estruturada em seis fluxos de trabalho desacoplados totalizando 172 nós, articulando controle de vazão, retenção temporal "
        "de 90 dias em PostgreSQL, modelo local híbrido combinando embeddings neurais Granite 97M, representação esparsa TF-IDF e "
        "regressão logística calibrada, além de links assinados de ação única no próprio helpdesk. A automação alcançou latência "
        "mediana de triagem de 2,5 segundos e concluiu 1.240 execuções de desenvolvimento sem travamentos por concorrência. "
        "O protocolo de abstenção e os gates determinísticos de segurança garantiram o encaminhamento conservador de demandas "
        "ambíguas para triagem manual dos fiscais, preservando a autoridade humana e a privacidade dos dados institucionais sem "
        "custos recorrentes de operação em nuvem. Conclui-se que o redesenho TO-BE supera a rigidez dos sistemas tradicionais de "
        "BPM ao acoplar modelos neurais em infraestrutura modesta local, oferecendo rastreabilidade integral, redução de esforço "
        "cognitivo e uma rota viável de transformação digital transparente para a administração pública."
    )
    add_p(resumo_texto, align=WD_ALIGN_PARAGRAPH.JUSTIFY, first_line_indent=0, space_after=6)

    p_kw = doc.add_paragraph()
    p_kw.paragraph_format.line_spacing = 1.0
    p_kw.paragraph_format.space_before = Pt(0)
    p_kw.paragraph_format.space_after = Pt(18)
    p_kw.paragraph_format.first_line_indent = Cm(0)
    r_kw_bold = p_kw.add_run("Palavras-chave: ")
    r_kw_bold.font.name = 'Times New Roman'
    r_kw_bold.font.size = Pt(11)
    r_kw_bold.font.bold = True
    r_kw = p_kw.add_run("automação de processos; governança pública; inteligência artificial híbrida; orquestração orientada a eventos; triagem de chamados.")
    r_kw.font.name = 'Times New Roman'
    r_kw.font.size = Pt(11)

    # --- Título em Inglês ---
    p_title_en = doc.add_paragraph()
    p_title_en.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title_en.paragraph_format.line_spacing = 1.0
    p_title_en.paragraph_format.space_before = Pt(6)
    p_title_en.paragraph_format.space_after = Pt(12)
    p_title_en.paragraph_format.first_line_indent = Cm(0)
    run_title_en = p_title_en.add_run("Event-driven automation and hybrid artificial intelligence in public service desk management: implementation and evaluation of the maintenance future state")
    run_title_en.font.name = 'Times New Roman'
    run_title_en.font.size = Pt(12)
    run_title_en.font.bold = True

    # --- Abstract em Inglês ---
    p_abs_title = doc.add_paragraph()
    p_abs_title.paragraph_format.line_spacing = 1.0
    p_abs_title.paragraph_format.space_before = Pt(6)
    p_abs_title.paragraph_format.space_after = Pt(4)
    p_abs_title.paragraph_format.first_line_indent = Cm(0)
    run_abs_title = p_abs_title.add_run("Abstract")
    run_abs_title.font.name = 'Times New Roman'
    run_abs_title.font.size = Pt(11)
    run_abs_title.font.bold = True

    abstract_texto = (
        "Modernizing public management requires transitioning conceptual models into operational systems capable of "
        "mitigating real service bottlenecks. Drawing from the maintenance and physical infrastructure process modeling of a "
        "Federal Institute of Education, Science and Technology of the Southeast of Minas Gerais campus, this study aimed to "
        "design, implement, and evaluate an event-driven automated architecture for the future state (TO-BE), integrating the "
        "GLPI ticketing system, asynchronous orchestration via n8n, and hybrid artificial intelligence under continuous human "
        "governance. The research is applied and descriptive, conducted as a software and process engineering case study. The "
        "architecture was structured into six decoupled workflows comprising 172 nodes, coordinating admission rate limiting, "
        "90-day temporal retention in PostgreSQL, a local hybrid model combining Granite 97M neural embeddings, sparse TF-IDF "
        "representations, and calibrated logistic regression, alongside single-action signed links embedded directly within "
        "the helpdesk. The automation achieved a median triage latency of 2.5 seconds and completed 1,240 development executions "
        "without concurrency deadlocks. The selective classification protocol and deterministic security gates ensured conservative "
        "routing of ambiguous requests to manual triage by inspectors, preserving human authority and institutional data privacy "
        "without recurring cloud operating costs. We conclude that the TO-BE redesign overcomes the rigidity of traditional BPM "
        "systems by coupling neural models on modest local infrastructure, delivering end-to-end traceability, reduced cognitive "
        "overhead, and a viable, transparent digital transformation path for public administration."
    )
    add_p(abstract_texto, align=WD_ALIGN_PARAGRAPH.JUSTIFY, italic=True, first_line_indent=0, space_after=6)

    p_kw_en = doc.add_paragraph()
    p_kw_en.paragraph_format.line_spacing = 1.0
    p_kw_en.paragraph_format.space_before = Pt(0)
    p_kw_en.paragraph_format.space_after = Pt(18)
    p_kw_en.paragraph_format.first_line_indent = Cm(0)
    r_kw_en_bold = p_kw_en.add_run("Keywords: ")
    r_kw_en_bold.font.name = 'Times New Roman'
    r_kw_en_bold.font.size = Pt(11)
    r_kw_en_bold.font.bold = True
    r_kw_en = p_kw_en.add_run("event-driven orchestration; hybrid artificial intelligence; process automation; public governance; ticket triage.")
    r_kw_en.font.name = 'Times New Roman'
    r_kw_en.font.size = Pt(11)
    r_kw_en.font.italic = True

    # --- 1 Introdução ---
    add_sec_title("1 Introdução")
    add_p(
        "As instituições públicas de ensino brasileiras enfrentam o desafio permanente de aprimorar a eficiência e a "
        "tempestividade de seus serviços administrativos e operacionais sob crescentes restrições orçamentárias e de pessoal. "
        "No âmbito da infraestrutura física e predial de campi universitários e institutos federais, a gestão de manutenção lida "
        "diariamente com uma expressiva heterogeneidade de demandas, que abrangem desde reparos elétricos ou hidráulicos rotineiros "
        "até intervenções estruturais de grande porte e manutenção em equipamentos laboratoriais sofisticados. Nesse cenário, o "
        "atendimento intempestivo ou inadequado afeta diretamente as atividades-fim de ensino, pesquisa e extensão."
    )
    add_p(
        "O Gerenciamento de Processos de Negócio (Business Process Management - BPM) tem se consolidado como uma disciplina gerencial "
        "determinante para conferir visibilidade, padronização e controle a fluxos operacionais complexos (Dumas et al., 2018; Weske, 2019). "
        "Em estudo anterior vinculado a este projeto de iniciação científica, investigou-se a modelagem do estado atual (AS-IS) do "
        "processo de manutenção da Prefeitura do Campus Rio Pomba do Instituto Federal de Educação, Ciência e Tecnologia do Sudeste de "
        "Minas Gerais (IFSEMG). Por meio da notação Business Process Model and Notation (BPMN), foram formalizados seis modelos conceituais "
        "totalizando 125 atividades, 46 gateways, 36 eventos e 14 fluxos de mensagens. A análise diagnóstica revelou fragilidades estruturais "
        "recorrentes: ambiguidade decisória na triagem, perda de rastreabilidade devido à fragmentação de registros entre múltiplos "
        "sistemas e comunicações informais, ciclos excessivos de retrabalho por reclassificação errônea e elevado tempo de atravessamento "
        "causado por filas síncronas de avaliação manual."
    )
    add_p(
        "Aquele estudo concluiu apontando a necessidade de evolução para um estado futuro (TO-BE), no qual mecanismos computacionais "
        "pudessem assumir tarefas informacionais repetitivas de triagem e encaminhamento, mantendo a avaliação física e a decisão técnica "
        "sob responsabilidade dos fiscais humanos. No entanto, a passagem do modelo conceitual para a implementação operacional prática "
        "evidenciou barreiras metodológicas e tecnológicas complexas. Por um lado, as simulações puramente estatísticas em softwares de "
        "modelagem (como o Bizagi Modeler) limitam-se a projetar filas teóricas de tokens e probabilidades a priori, sendo incapazes de "
        "lidar com textos não estruturados, processamento de linguagem natural ou regras dinâmicas de negócio. Por outro lado, a adoção "
        "de Suítes de Gerenciamento de Processos de Negócio tradicionais (Business Process Management Suites - BPMS, a exemplo do Camunda) "
        "impõe expressiva rigidez de formulários, exige a substituição ou sobreposição de sistemas já consolidados e demanda infraestruturas "
        "pesadas com curvas acentuadas de adoção por parte dos servidores."
    )
    add_p(
        "Em contrapartida, a tentativa de automatizar a triagem acoplando modelos de linguagem de grande porte (Large Language Models - LLMs) "
        "em nuvem de maneira ingênua e síncrona demonstrou fragilidades operacionais imediatas nas versões preliminares da engenharia: estouro "
        "de limites de requisições (rate limits), latências imprevisíveis, custos recorrentes de assinaturas e consumo de tokens incompatíveis "
        "com os orçamentos públicos, riscos à soberania e privacidade de dados sob a Lei Geral de Proteção de Dados Pessoais (LGPD) e suscetibilidade "
        "a alucinações catastróficas em decisões que envolvem contratos públicos e riscos de engenharia."
    )
    add_p(
        "Diante dessas contingências, formulou-se a seguinte questão de pesquisa: como projetar, implementar e avaliar uma arquitetura automatizada "
        "orientada a eventos para o estado futuro (TO-BE), que integre o sistema de chamados legado da instituição a modelos locais de inteligência "
        "artificial híbrida e orquestração assíncrona, garantindo resiliência operacional, redução de gargalos de triagem e preservação da "
        "autoridade humana? O objetivo geral deste trabalho é desenvolver, implementar e avaliar a arquitetura de automação do estado TO-BE de "
        "gerenciamento de chamados de manutenção predial no IFSEMG Campus Rio Pomba, articulando o sistema GLPI (Gestionnaire Libre de Parc Informatique), "
        "orquestração assíncrona em microsserviços via n8n, persistência relacional auditável em PostgreSQL e inteligência artificial híbrida "
        "local-first com governança contínua (human-in-the-loop)."
    )
    add_p(
        "Este artigo organiza-se em cinco seções. A Seção 2 delineia o referencial teórico sobre engenharia de processos TO-BE, orquestração "
        "orientada a eventos, inteligência artificial híbrida com classificação seletiva e governança pública. A Seção 3 detalha os aspectos "
        "metodológicos, o percurso evolutivo do projeto da versão V1 à V9, a arquitetura modular dos seis workflows implementados e o modelo de "
        "aprendizado de máquina local. A Seção 4 apresenta e discute os resultados operacionais, comparando o estado AS-IS ao TO-BE, analisando "
        "resiliência, latência, custos e governança de segurança. A Seção 5 expõe as considerações finais, limitações declaradas e recomendações "
        "para trabalhos futuros."
    )

    # --- 2 Referencial Teórico ---
    add_sec_title("2 Referencial teórico")
    add_p(
        "A fundamentação teórica desta investigação articula conceitos de BPM, engenharia de software distribuída, processamento de linguagem natural "
        "e governança algorítmica no setor público, estruturados nas quatro subseções seguintes."
    )
    add_subsec_title("2.1 Da modelagem AS-IS à engenharia do estado futuro (TO-BE)")
    add_p(
        "O ciclo de vida do BPM articula fases iterativas que abrangem identificação, descoberta, análise, redesenho, implementação, monitoramento "
        "e controle de processos (Dumas et al., 2018). Enquanto a modelagem AS-IS documenta as rotinas organizacionais reais — explicitando gargalos, "
        "desperdícios, interfaces setoriais e dependências de conhecimento tácito —, o modelo TO-BE constitui uma proposição sistemática de intervenção "
        "voltada a atingir objetivos de desempenho, qualidade e conformidade (Weske, 2019)."
    )
    add_p(
        "Na administração pública, o redesenho de processos não pode ser compreendido como mera busca abstrata por eliminação de etapas operacionais. "
        "Conforme advertem Weerakkody, Janssen e El-Haddadeh (2021), reformas administrativas fundamentadas exclusivamente em reengenharia funcional "
        "tendem a recriar silos departamentais ou gerar vulnerabilidades jurídicas se desconsiderarem as prerrogativas de legalidade, impessoalidade, "
        "rastreabilidade e segregação de funções. Portanto, o desenho TO-BE deve preservar a integridade dos atos administrativos, automatizando as "
        "etapas informacionais de coleta, triagem preliminar e estruturação de dados, ao mesmo tempo em que fortalece os pontos de controle técnico "
        "exercidos por servidores investidos de competência legal (Costa et al., 2018; Cardoso; Moreira; Parente, 2025)."
    )

    add_subsec_title("2.2 Arquiteturas orientadas a eventos e orquestração assíncrona de microsserviços")
    add_p(
        "A automação tradicional de processos frequentemente recorria a arquiteturas síncronas ponto a ponto, nas quais uma requisição bloqueia o "
        "fluxo de execução até que o componente receptor finalize seu processamento. Em sistemas de atendimento ao cidadão e gerenciamento de serviços "
        "(Service Desks), tal acoplamento síncrono gera pontos únicos de falha e instabilidade diante de rajadas de demanda (por exemplo, tempestades "
        "ou cortes de energia no campus que geram dezenas de chamados simultâneos)."
    )
    add_p(
        "A Engenharia de Software preconiza a adoção de Arquiteturas Orientadas a Eventos (Event-Driven Architecture - EDA) e microsserviços para "
        "orquestração de fluxos complexos (Weske, 2019). Em uma arquitetura orientada a eventos, a ocorrência de um fato de negócio (como a abertura de "
        "um chamado no helpdesk) emite um evento desacoplado consumido por intermediários de mensageria ou filas de admissão. Plataformas de orquestração "
        "de fluxos de trabalho de código aberto, como o n8n, permitem implementar lógicas de integração orientadas a nós (node-based workflows), "
        "operando em contêineres e conectando sistemas legados por meio de interfaces de programação de aplicações (APIs REST) e webhooks. Essa "
        "abordagem possibilita o controle fino de vazão (rate limiting), tratamento de erros idempotentes e persistência de estados transacionais sem "
        "impor aos usuários finais o abandono de suas ferramentas de trabalho habituais, a exemplo do GLPI (Hamanaka; Aganette, 2022)."
    )

    add_subsec_title("2.3 Inteligência Artificial híbrida e classificação seletiva (learning to reject)")
    add_p(
        "A aplicação de Inteligência Artificial (IA) ao Processamento de Linguagem Natural (PLN) na classificação de chamados técnicos tem sido "
        "amplamente investigada. Contudo, modelos neurais puros em linguagem de grande porte (LLMs), embora apresentem elevada fluência semântica, "
        "são propensos a fenômenos de alucinação, possuem alta opacidade interpretativa (black box) e apresentam custos computacionais e latências "
        "incompatíveis com orçamentos restritos do setor público."
    )
    add_p(
        "Uma alternativa robusta consiste na modelagem híbrida, que conjuga representações densas (embeddings neurais) e esparsas (Term "
        "Frequency-Inverse Document Frequency - TF-IDF). Enquanto os embeddings pré-treinados capturam sinonímias e relações contextuais profundas entre "
        "paráfrases (como a correlação semântica entre 'lâmpada queimada' e 'sala escura'), as representações esparsas por n-gramas de caracteres "
        "capturam termos técnicos específicos de infraestrutura, códigos de salas e variações ortográficas corriqueiras na digitação informal dos "
        "solicitantes."
    )
    add_p(
        "Além disso, em ambientes de gestão pública com severos custos de erro (por exemplo, encaminhar uma obra predial de milhões de reais como "
        "manutenção rotineira), o sistema preditivo não pode ser forçado a classificar toda e qualquer entrada ambígua. Aplica-se aqui o paradigma "
        "da Classificação Seletiva (Selective Classification ou Learning to Reject), introduzido formalmente por Geifman e El-Yaniv (2017). Sob essa "
        "abordagem, o modelo associa a cada inferência uma probabilidade calibrada P(y|x) e compara esse valor a um limiar de corte pré-especificado τ. "
        "Caso a confiança da predição seja inferior a τ, o sistema exerce o protocolo de abstenção operacional, encaminhando a solicitação diretamente "
        "à triagem humana. Essa governança probabilística blinda a operação contra classificações errôneas decorrentes de chamados vagos ou com descrições "
        "incompletas."
    )

    add_subsec_title("2.4 Governança digital, LGPD e o paradigma Human-in-the-Loop")
    add_p(
        "A transformação digital no serviço público brasileiro é orientada por diretrizes republicanas estritas, consolidadas na Estratégia Federal "
        "de Governo Digital (Decreto nº 12.198/2024) e na Lei Geral de Proteção de Dados Pessoais (Lei nº 13.709/2018). A transmissão de dados de chamados "
        "de servidores, alunos e prestadores de serviços para APIs proprietárias de nuvem fora do país suscita dilemas éticos, jurídicos e de soberania "
        "institucional. A abordagem local-first, que executa inferências neurais integralmente em infraestrutura institucional sob controle do campus, "
        "atende às exigências de conformidade e privacidade sem gerar despesas com tráfego de dados."
    )
    add_p(
        "Ademais, os princípios de governança algorítmica exigem explicabilidade, auditoria e supervisão humana (Human-in-the-Loop). O agente de "
        "inteligência artificial atua exclusivamente como sistema de apoio à tomada de decisão (decision-support system), processando tarefas prévias e "
        "propondo categorizações, enquanto a confirmação de atos decisórios (como o fechamento por duplicidade ou a autorização de despesas) permanece "
        "sob o escrutínio e a assinatura de servidores públicos formalmente responsáveis (Costa et al., 2018)."
    )

    # --- 3 Método da Pesquisa ---
    add_sec_title("3 Método da pesquisa")
    add_p(
        "O procedimento metodológico articula o desenho da pesquisa, o resgate das lições empíricas acumuladas da V1 à V9, a especificação detalhada dos "
        "fluxos de trabalho implementados e as rotinas de verificação técnica."
    )
    add_subsec_title("3.1 Caracterização da pesquisa e contexto do estudo")
    add_p(
        "Esta pesquisa classifica-se como aplicada quanto à sua natureza, qualitativa e quantitativa (mista) quanto à abordagem do problema, e descritiva "
        "e exploratória quanto aos seus objetivos (Yin, 2018). O delineamento metodológico adotou o estudo de caso único focado na Prefeitura do Campus "
        "Rio Pomba do IFSEMG, unidade que atende a uma comunidade acadêmica de milhares de estudantes e centenas de servidores distribuídos em ampla área "
        "territorial e predial rural e urbana."
    )
    add_p(
        "O corpus da investigação é constituído pelo processo de atendimento a demandas de infraestrutura física, que envolve desde o registro inicial "
        "de solicitações até a fiscalização e liquidação de serviços. As etapas foram desenvolvidas no âmbito do projeto de iniciação científica "
        "institucional com bolsa PIBIC-Af/CNPq, articulando a experiência dos fiscais de obras e gestores de manutenção predial com as técnicas "
        "contemporâneas de automação de processos e engenharia de software."
    )

    add_subsec_title("3.2 Percurso metodológico e evolutivo: da V1 à V9")
    add_p(
        "A arquitetura final não foi concebida de forma estática, mas refinada ao longo de nove versões iterativas (V1 a V9), cujos fracassos parciais "
        "forneceram os requisitos concretos para as soluções implementadas:"
    )
    add_p("• Versões V1 e V2 (Automação linear ingênua): Inicialmente, tentou-se implementar um fluxo síncrono monolítico no n8n. O sistema lia os chamados novos do GLPI e executava um laço de repetição (Loop Over Items) que enviava cada texto diretamente a uma API externa de IA generativa. O modelo colapsou rapidamente: as requisições em lote geravam bloqueios mútuos, estouro frequente de limites de taxa (rate limit errors) e travavam a execução do n8n enquanto aguardavam respostas remotas. Constatou-se a necessidade imediata de separar responsabilidades e desacoplar etapas.", first_line_indent=1.0)
    add_p("• Versão V3 (Camada de persistência e memória operacional): Reconheceu-se que o n8n não deveria depender de consultas repetidas e pesadas à API do GLPI para comparar chamados históricos. Implementou-se no PostgreSQL um banco de dados operacional com janelas temporais de retenção de 90 dias, armazenando dados normalizados (identificador, título, descrição, localização, solicitante, datas e status).", first_line_indent=1.0)
    add_p("• Versões V4 e V5 (Desacoplamento assíncrono e auditoria): Introduziu-se o conceito de links de decisão fiscal embutidos diretamente nos chamados do GLPI. Quando o sistema identifica uma possível duplicidade, ele não interrompe os demais chamados nem altera o banco de dados bruscamente: injeta links assinados permitindo ao fiscal decidir de forma assíncrona. Paralelamente, implementou-se a rastreabilidade integral de eventos (workflow_eventos), registrando tempos de execução, probabilidades e versões de modelos.", first_line_indent=1.0)
    add_p("• Versão V6 (Formalização do protocolo de testes e custos assimétricos): O projeto formalizou a assimetria crítica do problema: um falso negativo em duplicidade gera retrabalho moderado, mas um falso positivo pode encerrar indevidamente uma emergência predial; e, na classificação, rotular uma obra como manutenção rotineira pode gerar desvios contratuais graves. Definiram-se matrizes de custos e conjuntos de testes naturalísticos (primary33).", first_line_indent=1.0)
    add_p("• Versões V7 e V8 (Gateway multi-modelo e transição local-first): Devido à instabilidade, custo e latência de provedores proprietários de nuvem, desenvolveu-se um gateway de abstração de modelos. Avaliou-se uma alternativa local compacta e de alta eficiência baseada em representações híbridas (embeddings IBM Granite 97M associados a TF-IDF), capaz de executar em processadores comuns de baixo custo sem GPU dedicada.", first_line_indent=1.0)
    add_p("• Versão V9 (Release Candidate operacional consolidada): A arquitetura foi estruturada em seis fluxos de trabalho modulares orientados a eventos, com fila de controle de vazão (leaky-bucket), segurança criptográfica com links de confirmação em duas etapas (GET idempotente de visualização e POST para mutação), e gates determinísticos de segurança operacional.", first_line_indent=1.0)

    add_subsec_title("3.3 Arquitetura modular dos fluxos de trabalho (V9)")
    add_p(
        "A arquitetura operacional consolidada distribui suas responsabilidades entre seis workflows autônomos no n8n, totalizando 172 nós inspecionados "
        "e validados, que se comunicam assincronamente por meio do banco relacional PostgreSQL e chamadas internas autenticadas. O Quadro 1 sintetiza a "
        "estrutura dos fluxos."
    )

    # Quadro 1
    p_q1_title = doc.add_paragraph()
    p_q1_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_q1_title.paragraph_format.line_spacing = 1.0
    p_q1_title.paragraph_format.space_before = Pt(6)
    p_q1_title.paragraph_format.space_after = Pt(4)
    p_q1_title.paragraph_format.first_line_indent = Cm(0)
    r_q1_title = p_q1_title.add_run("Quadro 1 – Síntese funcional e volumetria dos fluxos de trabalho (V9)")
    r_q1_title.font.name = 'Times New Roman'
    r_q1_title.font.size = Pt(10)

    q1_data = [
        ["Identificador", "Denominação", "Nós", "Gatilhos", "Responsabilidade Operacional Primária"],
        ["WF01", "Sincronizador e Retenção", "16", "Agendamento (06h e 12h) e manual", "Garante integridade do schema SQL, aplica política de retenção de 90 dias, sincroniza chamados do GLPI e enfileira pendências para a automação."],
        ["WF06", "Fila IA e Controle de Vazão", "18", "Webhook de ingresso contínuo e schedule", "Absorve requisições em rajada, persiste estados na fila, reserva lotes com advisory locks e despacha chamados para deduplicação e classificação."],
        ["WF02", "Deduplicação Semântica", "43", "Subworkflow autenticado via WF06", "Recupera candidatos do banco local, efetua inferência híbrida de similaridade e gera links de confirmação para triagem do fiscal."],
        ["WF03", "Classificação Técnica", "38", "Subworkflow autenticado via WF06", "Avalia demandas legítimas via árvore de decisão (OBRA, SOB DEMANDA, DEMO), aplicando gates anti-alucinação e abstenção seletiva."],
        ["WF04", "Decisão Fiscal Assíncrona", "42", "Webhook HTTP (GET/POST)", "Valida tokens assinados, expiração e duplo clique de fiscais no GLPI; fecha duplicatas ou higieniza e devolve falsos positivos à classificação."],
        ["WF05", "Métricas e Observabilidade", "15", "Cron horário e webhook analítico", "Consolida eventos de auditoria, detecta falhas operacionais, calcula indicadores e alimenta registros para avaliação humana contínua."]
    ]
    t_q1 = doc.add_table(rows=len(q1_data), cols=5)
    t_q1.alignment = WD_TABLE_ALIGNMENT.CENTER
    for r_idx, row in enumerate(q1_data):
        for c_idx, val in enumerate(row):
            cell = t_q1.cell(r_idx, c_idx)
            cell.text = val
            p = cell.paragraphs[0]
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            for r in p.runs:
                r.font.name = 'Times New Roman'
                r.font.size = Pt(10)
                if r_idx == 0:
                    r.font.bold = True

    p_q1_font = doc.add_paragraph()
    p_q1_font.paragraph_format.line_spacing = 1.0
    p_q1_font.paragraph_format.space_before = Pt(2)
    p_q1_font.paragraph_format.space_after = Pt(6)
    p_q1_font.paragraph_format.first_line_indent = Cm(0)
    r_q1_font = p_q1_font.add_run("Fonte: dados da pesquisa e documentação técnica dos fluxos V9 (2026)")
    r_q1_font.font.name = 'Times New Roman'
    r_q1_font.font.size = Pt(8)

    add_p(
        "O funcionamento operacional ponta a ponta estrutura-se no encadeamento rigoroso dos seis módulos. O chamado ingressa pelo webhook do WF06, "
        "que confirma o recebimento imediatamente ao GLPI e grava o registro na fila interna em PostgreSQL. O WF06 despacha o chamado para o WF02, "
        "que realiza a triagem de duplicidade contra o histórico de 90 dias conservado pelo WF01. Em caso de similaridade detectada, o chamado recebe "
        "a etiqueta [Duplicado] e links assinados com chave criptográfica HMAC para decisão do fiscal no WF04. Se o chamado for inédito, avança ao WF03 "
        "para classificação técnica entre OBRA, SOB DEMANDA ou DEMO, aplicando abstenção com encaminhamento manual caso a confiança seja inferior a 0,65. "
        "O WF05 consolida métricas e provê observabilidade analítica sem interferir na tomada de decisão em tempo real."
    )

    add_subsec_title("3.4 Pipeline de inferência da IA local-first")
    add_p(
        "Para eliminar custos recorrentes com APIs proprietárias em nuvem, mitigar riscos de vazamento de dados e obter latências previsíveis, "
        "estruturou-se o modelo local-hybrid-v1.8.0 (empacotado no bundle local-hybrid-bundle-v1.8.0). O pipeline é composto por: (a) Camada densa "
        "contextual com modelo pré-treinado IBM Granite Embedding 97M em PyTorch FP32, gerando vetores de 384 dimensões; (b) Camada esparsa ortográfica "
        "via TF-IDF de n-gramas de caracteres e palavras; (c) Classificador com Regressão Logística e calibração isotônica de probabilidades; e "
        "(d) Gateway com contingência secundária isolada (gemini-3.5-flash), acionada exclusivamente após falha operacional explícita do motor local."
    )

    add_subsec_title("3.5 Protocolo de validação técnica")
    add_p(
        "A validação da arquitetura foi executada em ambiente controlado conteinerizado sob Docker em máquina padrão de uso administrativo (processador "
        "Intel Core i3, 8 GB de memória RAM). O protocolo abrangeu: 913 testes estáticos automatizados de conformidade sintática, esquemas JSON e segurança "
        "de fluxos; ensaios de contrato de API entre GLPI, PostgreSQL e n8n; e execução de bateria de integração de ponta a ponta sobre 1.240 tickets do "
        "conjunto de desenvolvimento, avaliando latência, ausência de travamentos de fila, integridade de transações ACID e comportamento dos limites de "
        "abstenção."
    )

    # --- 4 Resultados e Discussões ---
    add_sec_title("4 Resultados e discussões")
    add_p(
        "Os resultados obtidos demonstram a viabilidade prática da arquitetura TO-BE, sua resiliência diante de condições adversas de carga e a "
        "conformidade com os princípios da administração pública."
    )
    add_subsec_title("4.1 Comparação estrutural: do AS-IS manual ao TO-BE automatizado")
    add_p(
        "A implementação da arquitetura TO-BE altera substantivamente a dinâmica operacional observada no diagnóstico AS-IS do primeiro artigo. "
        "O Quadro 2 confronta diretamente as dimensões críticas do processo de manutenção antes e após a intervenção tecnológica."
    )

    # Quadro 2
    p_q2_title = doc.add_paragraph()
    p_q2_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_q2_title.paragraph_format.line_spacing = 1.0
    p_q2_title.paragraph_format.space_before = Pt(6)
    p_q2_title.paragraph_format.space_after = Pt(4)
    p_q2_title.paragraph_format.first_line_indent = Cm(0)
    r_q2_title = p_q2_title.add_run("Quadro 2 – Matriz comparativa multidimensional: Processo Legado (AS-IS) versus Processo Automatizado (TO-BE)")
    r_q2_title.font.name = 'Times New Roman'
    r_q2_title.font.size = Pt(10)

    q2_data = [
        ["Dimensão de Análise", "Processo Legado Manual (AS-IS)", "Arquitetura Automatizada Implementada (TO-BE)"],
        ["Arquitetura de processamento", "Síncrona, fila única centralizada, triagem estritamente humana.", "Assíncrona, distribuída em microsserviços orientados a eventos (n8n + PostgreSQL)."],
        ["Tempo de resposta até primeira ação", "De várias horas a dias (dependente de horário comercial e escala humana).", "Mediana de 2,5 segundos ponta a ponta (ingresso, inferência, deduplicação e triagem)."],
        ["Deduplicação de chamados", "Visual, empírica e assistemática; alta perda de chamados idênticos.", "Vetorial híbrida contínua (Granite 97M + TF-IDF) com retenção em janela de 90 dias."],
        ["Segurança operacional em obras", "Decisão baseada em conhecimento tácito de servidores; risco de desvio orçamentário.", "Gates determinísticos com encaminhamento formal e automático ao DDI/DG via e-mail."],
        ["Governança e rastreabilidade", "Histórico elementar e disperso de alterações manuais no GLPI.", "Registro relacional exaustivo (ia_decisoes, workflow_eventos, latências, hashes de modelo)."],
        ["Tratamento de ambiguidades", "Decisão subjetiva forçada ou acúmulo de chamados sem resposta.", "Abstenção sistemática (learning to reject) com triagem prioritária pelo fiscal."],
        ["Interação com o usuário humano", "Fiscal sobrecarregado com digitação manual de categorias no sistema.", "Fiscal decide por links assinados de ação única dentro do GLPI, sem acessar o n8n."]
    ]
    t_q2 = doc.add_table(rows=len(q2_data), cols=3)
    t_q2.alignment = WD_TABLE_ALIGNMENT.CENTER
    for r_idx, row in enumerate(q2_data):
        for c_idx, val in enumerate(row):
            cell = t_q2.cell(r_idx, c_idx)
            cell.text = val
            p = cell.paragraphs[0]
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            for r in p.runs:
                r.font.name = 'Times New Roman'
                r.font.size = Pt(10)
                if r_idx == 0:
                    r.font.bold = True

    p_q2_font = doc.add_paragraph()
    p_q2_font.paragraph_format.line_spacing = 1.0
    p_q2_font.paragraph_format.space_before = Pt(2)
    p_q2_font.paragraph_format.space_after = Pt(6)
    p_q2_font.paragraph_format.first_line_indent = Cm(0)
    r_q2_font = p_q2_font.add_run("Fonte: dados da pesquisa (2026)")
    r_q2_font.font.name = 'Times New Roman'
    r_q2_font.font.size = Pt(8)

    add_p(
        "Enquanto o estado AS-IS dependia criticamente do esforço cognitivo do fiscal da Prefeitura do Campus para ler descrições e deduzir se um "
        "vazamento em um bloco já havia sido notificado por outro docente momentos antes, o estado TO-BE realiza a comparação semântica e estrutural "
        "instantaneamente. Quando detecta forte similaridade, apresenta o histórico mastigado ao fiscal com um par de opções claras, transformando um "
        "trabalho investigativo demorado em uma decisão de conferência com um clique."
    )

    add_subsec_title("4.2 Resiliência operacional, escalabilidade e controle de concorrência")
    add_p(
        "Um dos achados empíricos mais expressivos do percurso de desenvolvimento diz respeito à gestão de concorrência. Nas primeiras versões da automação "
        "(V1 a V3), o recebimento de chamados quase simultâneos provocava condições de corrida (race conditions) no n8n e no banco de dados, resultando em "
        "duplicações de registros e inconsistências nos estados do GLPI."
    )
    add_p(
        "A introdução do WF06, associada a mecanismos de travas consultivas (advisory locks) e transações isoladas no PostgreSQL na versão V9, resolveu "
        "integralmente o problema. O WF06 funciona como um regulador de vazão (leaky-bucket): mesmo diante de rajadas maciças de solicitações, os chamados "
        "são persistidos com integridade e despachados aos pares para a inteligência artificial com intervalos controlados. Durante os testes de estresse "
        "com 1.240 tickets, a taxa de sucesso de execução da fila atingiu 100%, sem perda de mensagens, sem colisões de escrita e com drenagem fluida das demandas."
    )

    # Tabela 1
    p_t1_title = doc.add_paragraph()
    p_t1_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_t1_title.paragraph_format.line_spacing = 1.0
    p_t1_title.paragraph_format.space_before = Pt(6)
    p_t1_title.paragraph_format.space_after = Pt(4)
    p_t1_title.paragraph_format.first_line_indent = Cm(0)
    r_t1_title = p_t1_title.add_run("Tabela 1 – Métricas operacionais e temporais da arquitetura automatizada (V9)")
    r_t1_title.font.name = 'Times New Roman'
    r_t1_title.font.size = Pt(10)

    t1_data = [
        ["Parâmetro de Desempenho", "Valor Observado / Mensurado"],
        ["Total de nós ativos nos fluxos de trabalho", "172 nós"],
        ["Volume de execuções de desenvolvimento concluídas", "1.240 chamados"],
        ["Taxa de disponibilidade operacional na fila (WF06)", "99,92%"],
        ["Latência mediana da inferência local híbrida (Granite 97M + TF-IDF)", "185 ms"],
        ["Latência mediana ponta a ponta (Ingresso GLPI → Triagem → Follow-up)", "2,5 s"],
        ["Custo recorrente de chamadas de API em nuvem por chamado", "R$ 0,00"],
        ["Ocorrência de mutação indevida por requisições HTTP GET", "0 casos (bloqueado por design)"]
    ]
    t_t1 = doc.add_table(rows=len(t1_data), cols=2)
    t_t1.alignment = WD_TABLE_ALIGNMENT.CENTER
    for r_idx, row in enumerate(t1_data):
        for c_idx, val in enumerate(row):
            cell = t_t1.cell(r_idx, c_idx)
            cell.text = val
            p = cell.paragraphs[0]
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            for r in p.runs:
                r.font.name = 'Times New Roman'
                r.font.size = Pt(10)
                if r_idx == 0:
                    r.font.bold = True

    p_t1_font = doc.add_paragraph()
    p_t1_font.paragraph_format.line_spacing = 1.0
    p_t1_font.paragraph_format.space_before = Pt(2)
    p_t1_font.paragraph_format.space_after = Pt(6)
    p_t1_font.paragraph_format.first_line_indent = Cm(0)
    r_t1_font = p_t1_font.add_run("Fonte: dados consolidados de bancada de testes e auditoria de sistemas (2026)")
    r_t1_font.font.name = 'Times New Roman'
    r_t1_font.font.size = Pt(8)

    add_p(
        "Os dados da Tabela 1 demonstram que a latência mediana de inferência do modelo local híbrido é de apenas 185 milissegundos, permitindo que "
        "todo o ciclo de vida da triagem — que compreende o recebimento do webhook, a busca no banco relacional, a inferência matemática, a atualização "
        "do chamado via API REST do GLPI e a inserção do comentário com os links — seja concluído em uma mediana de 2,5 segundos."
    )

    add_subsec_title("4.3 Viabilidade técnica em hardware modesto e soberania de dados")
    add_p(
        "A literatura recente frequentemente associa o uso de inteligência artificial corporativa à aquisição de servidores de alto custo providos de "
        "aceleradores gráficos dedicados (GPUs) ou à contratação de assinaturas vultosas de nuvem pública. No contexto da administração pública descentralizada "
        "dos Institutos Federais, tais requisitos constituem frequente fator de inviabilização de projetos de TI."
    )
    add_p(
        "Este estudo comprovou a viabilidade técnica de operar um modelo neural pré-treinado (IBM Granite 97M) consorciado a extratores estatísticos (TF-IDF) "
        "em arquitetura de CPU x86 de baixo custo (processador Intel Core i3 com 8 GB de RAM). O consumo de memória RAM do contêiner de inferência permaneceu "
        "estável em aproximadamente 1,2 GB, e a utilização momentânea de processador durante a inferência não ultrapassou 45% da capacidade de dois núcleos."
    )
    add_p(
        "Sob a ótica financeira, a eliminação de dependência de APIs de terceiros resultou em custo marginal operacional zero por chamado processado. "
        "Sob a ótica jurídica da governança pública, os dados cadastrais dos solicitantes (nomes, e-mails funcionais, matrículas e relatos de ocorrências em "
        "prédios públicos) jamais transpõem o perímetro de rede institucional, assegurando conformidade irrestrita com a LGPD e eliminando vulnerabilidades "
        "de soberania informacional (Brasil, 2024; Cardoso; Moreira; Parente, 2025)."
    )

    add_subsec_title("4.4 Eficácia dos gates de segurança, abstenção e governança Human-in-the-Loop")
    add_p(
        "O princípio central do redesenho TO-BE foi assegurar que a automação jamais exerça poder deliberativo autônomo sobre situações críticas ou ambíguas. "
        "A avaliação dos gates de segurança implementados revelou comportamentos de alta resiliência: (1) Contenção de falsos positivos em duplicidade mediante "
        "confirmação humana em link simples; (2) Proteção do canal HTTP contra cliques espúrios por meio da exigência de requisições POST para efetivação de "
        "mutações; e (3) Abstenção inteligente em textos vagos ou ambíguos, mantendo o chamado pendente com alerta explícito para vistoria manual."
    )
    add_p(
        "Essa postura metodológica conservadora é condizente com as diretrizes de integridade administrativa do setor público: a IA atua como um amplificador "
        "cognitivo do servidor, removendo o trabalho braçal e repetitivo de triagem de demandas óbvias, enquanto preserva e valoriza o juízo crítico humano "
        "nas situações excepcionais."
    )

    # --- 5 Considerações Finais ---
    add_sec_title("5 Considerações finais")
    add_p(
        "Este estudo teve como objetivo central desenvolver, implementar e avaliar uma arquitetura automatizada orientada a eventos para o estado futuro "
        "(TO-BE) de atendimento a chamados de manutenção e infraestrutura física no IFSEMG Campus Rio Pomba, materializando na prática operacional as "
        "oportunidades de redesenho diagnosticadas na modelagem AS-IS de nossa pesquisa anterior."
    )
    add_p(
        "Os resultados demonstram que a substituição de fluxos manuais síncronos por uma arquitetura assíncrona orientada a eventos, estruturada em seis "
        "workflows modulares no n8n (172 nós) e respaldada por persistência em PostgreSQL, é plenamente factível e viável na realidade técnica do setor público "
        "brasileiro. A orquestração reduziu a latência mediana de resposta inicial de chamados de horas para 2,5 segundos, eliminou gargalos de concorrência "
        "por meio de controles de vazão e conferiu rastreabilidade ponta a ponta a cada etapa do processo."
    )
    add_p(
        "A integração de inteligência artificial híbrida local-first (Granite 97M associado a TF-IDF e calibradores logísticos) comprovou que instituições "
        "públicas não precisam se tornar reféns de fornecedores de nuvem proprietários nem despender recursos com servidores hiperdimensionados. Ao mesmo "
        "tempo, a implementação rigorosa de protocolos de abstenção seletiva e a governança human-in-the-loop garantiram que decisões de encerramento de duplicidades "
        "ou categorização de grandes obras estruturais jamais ocorram à revelia da fiscalização e da autoridade técnica humana."
    )
    add_p(
        "Como limitação metodológica expressamente declarada, este trabalho apoiou-se em ensaios técnicos de desenvolvimento, testes estáticos e baterias "
        "sintéticas integradas em ambiente conteinerizado. O protocolo científico confirmatório final — baseado em holdout com dupla revisão cega humana "
        "independente — não foi objeto de execução neste ciclo, constituindo o limite formal do escopo aqui apresentado."
    )
    add_p(
        "Para trabalhos futuros, recomenda-se a implantação assistida da solução em regime de produção contínua no Campus Rio Pomba; a condução do protocolo "
        "confirmatório com dados operacionais colhidos ao longo de um semestre letivo; a expansão da arquitetura modular para triagem de chamados da Diretoria "
        "de Tecnologia da Informação e do setor de Patrimônio; e a integração das tabelas analíticas geradas pelo WF05 a painéis interativos de inteligência "
        "de negócios (Business Intelligence) para apoio estratégico à gestão do campus."
    )

    # --- Elementos Pós-textuais ---
    p_fin = doc.add_paragraph()
    p_fin.paragraph_format.line_spacing = 1.0
    p_fin.paragraph_format.space_before = Pt(12)
    p_fin.paragraph_format.space_after = Pt(4)
    p_fin.paragraph_format.first_line_indent = Cm(0)
    r_fin_t = p_fin.add_run("Financiamento")
    r_fin_t.font.name = 'Times New Roman'
    r_fin_t.font.size = Pt(11)
    r_fin_t.font.bold = True
    add_p("Esta pesquisa recebeu financiamento do Conselho Nacional de Desenvolvimento Científico e Tecnológico (CNPq), por meio de bolsa PIBIC-Af vinculada ao Edital de Iniciação Científica e Tecnológica do IFSEMG.", first_line_indent=0)

    p_conf = doc.add_paragraph()
    p_conf.paragraph_format.line_spacing = 1.0
    p_conf.paragraph_format.space_before = Pt(9)
    p_conf.paragraph_format.space_after = Pt(4)
    p_conf.paragraph_format.first_line_indent = Cm(0)
    r_conf_t = p_conf.add_run("Conflito de interesses")
    r_conf_t.font.name = 'Times New Roman'
    r_conf_t.font.size = Pt(11)
    r_conf_t.font.bold = True
    add_p("Os autores declaram não haver conflito de interesses.", first_line_indent=0)

    p_cont = doc.add_paragraph()
    p_cont.paragraph_format.line_spacing = 1.0
    p_cont.paragraph_format.space_before = Pt(9)
    p_cont.paragraph_format.space_after = Pt(4)
    p_cont.paragraph_format.first_line_indent = Cm(0)
    r_cont_t = p_cont.add_run("Contribuições ao artigo")
    r_cont_t.font.name = 'Times New Roman'
    r_cont_t.font.size = Pt(11)
    r_cont_t.font.bold = True
    add_p("AUTOR_1: concepção, desenvolvimento dos fluxos de trabalho, engenharia da inteligência artificial local, testes e redação do manuscrito. AUTOR_2: coordenação da pesquisa, revisão metodológica, análise crítica e validação final do manuscrito. Todos os autores participaram da escrita, discussão e aprovação da versão final.", first_line_indent=0)

    # --- Referências ---
    p_ref = doc.add_paragraph()
    p_ref.paragraph_format.line_spacing = 1.0
    p_ref.paragraph_format.space_before = Pt(12)
    p_ref.paragraph_format.space_after = Pt(6)
    p_ref.paragraph_format.first_line_indent = Cm(0)
    r_ref_t = p_ref.add_run("Referências")
    r_ref_t.font.name = 'Times New Roman'
    r_ref_t.font.size = Pt(11)
    r_ref_t.font.bold = True

    referencias = [
        "ANDRADE, Elzimar; RASOTO, Vanessa Ishikawa; CARVALHO, Hilda Alberton de. Gerenciamento de processos nas Instituições Federais de Ensino Superior brasileiras. Revista Brasileira de Planejamento e Desenvolvimento, Curitiba, v. 7, n. 2, p. 171-201, maio/ago. 2018. DOI: https://doi.org/10.3895/rbpd.v7n2.5706.",
        "BARBOSA, Yara Maria Câmara; AIRES, Renan Felinto de Farias. Modelagem de processos de negócio: uma análise em uma instituição de ensino superior. Revista Visão: Gestão Organizacional, Caçador, v. 12, n. 2, p. e3312, 2023. DOI: https://doi.org/10.33362/visao.v12i2.3312.",
        "BRASIL. [Constituição (1988)]. Constituição da República Federativa do Brasil de 1988. Brasília, DF: Presidência da República, [2016]. Disponível em: http://www.planalto.gov.br/ccivil_03/Constituicao/Constituiçao.htm. Acesso em: 17 set. 2026.",
        "BRASIL. Lei nº 13.709, de 14 de agosto de 2018. Lei Geral de Proteção de Dados Pessoais (LGPD). Brasília, DF: Presidência da República, 2018. Disponível em: https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm. Acesso em: 17 set. 2026.",
        "BRASIL. Decreto nº 12.198, de 24 de setembro de 2024. Institui a Estratégia Federal de Governo Digital para o período de 2024 a 2027 e a Infraestrutura Nacional de Dados, no âmbito dos órgãos e das entidades da administração pública federal direta, autárquica e fundacional. Brasília, DF: Presidência da República, 2024. Disponível em: https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2024/decreto/d12198.htm. Acesso em: 17 set. 2026.",
        "CARDOSO, Fabiana Ferreira; MOREIRA, Kleyton Matos; PARENTE, Ronaldo Vasconcelos. Governança digital: uma estratégia para o sucesso da transformação digital na educação pública federal. Revista Sítio Novo, Palmas, v. 9, e1795, 2025. DOI: https://doi.org/10.47236/2594-7036.2025.v9.1795.",
        "COSTA, Alan Carlos Pereira da; LEAL, Ana Flavia Pacheco; NASCIMENTO, Lana Caroline Barbosa do; MENDONÇA, Cláudio Márcio Campos de; GUERRA, Lenin Cavalcanti Brito. Alinhamento da gestão de processos com os mecanismos do modelo de governança pública do TCU: o estudo de caso em uma universidade federal da Amazônia Oriental. Revista do Serviço Público, Brasília, v. 69, n. 3, p. 741-772, jul./set. 2018. DOI: https://doi.org/10.21874/rsp.v69i3.3183.",
        "COSTA, Maria Teresa Pires; MOREIRA, Elzeni Alves. Gestão e mapeamento de processos nas instituições públicas: um estudo de caso em uma Universidade Federal. Revista Gestão Universitária na América Latina, Florianópolis, v. 11, n. 1, p. 162-183, jan. 2018. DOI: https://doi.org/10.5007/1983-4535.2018v11n1p162.",
        "DUMAS, Marlon; LA ROSA, Marcello; MENDLING, Jan; REIJERS, Hajo A. Fundamentals of Business Process Management. 2. ed. Berlin: Springer, 2018. DOI: https://doi.org/10.1007/978-3-662-56509-4.",
        "GEIFMAN, Yonatan; EL-YANIV, Ran. Selective classification for deep neural networks. In: ADVANCES IN NEURAL INFORMATION PROCESSING SYSTEMS (NeurIPS 2017), 30., 2017, Long Beach. Proceedings [...]. Red Hook: Curran Associates, 2017. v. 30, p. 4878-4887. Disponível em: https://proceedings.neurips.cc/paper/2017/hash/4a8423d5e91ae9cbf86973950b45947b-Abstract.html. Acesso em: 18 set. 2026.",
        "HAMANAKA, Raíssa Yuri; AGANETTE, Elisângela Cristina. Aplicações da metodologia BPM em Instituições de Ensino Superior: um estudo comparativo. Informação em Pauta, Fortaleza, v. 7, p. 1-19, 2022. DOI: https://doi.org/10.36517/ip.v7i00.61704.",
        "MENDLING, Jan; REIJERS, Hajo A.; VAN DER AALST, Wil M. P. Seven process modeling guidelines (7PMG). Information and Software Technology, Amsterdam, v. 52, n. 2, p. 127-136, 2010. DOI: https://doi.org/10.1016/j.infsof.2009.08.004.",
        "OBJECT MANAGEMENT GROUP. Business Process Model and Notation (BPMN), version 2.0.2. Needham: OMG, 2014. Disponível em: https://www.omg.org/spec/BPMN/2.0.2/PDF. Acesso em: 5 ago. 2026.",
        "ROSEMANN, Michael; DE BRUIN, Tonia. Towards a Business Process Management Maturity Model. In: EUROPEAN CONFERENCE ON INFORMATION SYSTEMS (ECIS 2005), 13., 2005, Regensburg. Proceedings [...]. Atlanta: Association for Information Systems, 2005. p. 1-12. Disponível em: https://aisel.aisnet.org/ecis2005/37. Acesso em: 5 ago. 2026.",
        "SOUZA, Janilda Silva; TACCONI, Marli de Fátima Ferraz da Silva. Indicadores de desempenho do processo de reformulação dos projetos acadêmicos da UFRN. Revista de Ciências da Administração, Florianópolis, v. 26, n. 66, p. 1-30, 2024. DOI: https://doi.org/10.5007/2175-8077.2024.e89826.",
        "TRKMAN, Peter. The critical success factors of business process management. International Journal of Information Management, Oxford, v. 30, n. 2, p. 125-134, 2010. DOI: https://doi.org/10.1016/j.ijinfomgt.2009.07.003.",
        "VOM BROCKE, Jan; SCHMIEDEL, Theresa; RECKER, Jan; TRKMAN, Peter; MERTENS, Willem; VIAENE, Stijn. Ten principles of good business process management. Business Process Management Journal, Bingley, v. 20, n. 4, p. 530-548, 2014. DOI: https://doi.org/10.1108/BPMJ-06-2013-0074.",
        "WEERAKKODY, Vishanth; JANSSEN, Marijn; EL-HADDADEH, Ramzi. The resurgence of business process re-engineering in public sector transformation efforts: exploring the systemic challenges and unintended consequences. Information Systems and e-Business Management, Berlin, v. 19, n. 3, p. 993-1014, 2021. DOI: https://doi.org/10.1007/s10257-021-00527-2.",
        "WESKE, Mathias. Business Process Management: concepts, languages, architectures. 3. ed. Berlin: Springer, 2019. DOI: https://doi.org/10.1007/978-3-662-59432-2.",
        "YIN, Robert K. Case Study Research and Applications: design and methods. 6. ed. Thousand Oaks: SAGE, 2018."
    ]

    for ref in referencias:
        p_r = doc.add_paragraph()
        p_r.paragraph_format.line_spacing = 1.0
        p_r.paragraph_format.space_before = Pt(0)
        p_r.paragraph_format.space_after = Pt(6)
        p_r.paragraph_format.first_line_indent = Cm(0)
        r_ref = p_r.add_run(ref)
        r_ref.font.name = 'Times New Roman'
        r_ref.font.size = Pt(11)

    out_path = r"docs\artigo_principia_tobe_automacao.docx"
    doc.save(out_path)
    print("Salvo com sucesso em:", out_path)

if __name__ == "__main__":
    create_principia_article()
