# Política de segurança

## Versões com suporte

Somente a versão mais recente publicada, ou o commit mais recente da branch
principal antes da primeira versão, recebe correções de segurança. Este projeto
é um protótipo acadêmico e não deve ser tratado como serviço oficial ou
implantação pronta para produção.

## Como relatar uma vulnerabilidade

Não abra uma issue pública contendo credenciais, tokens, dados institucionais,
dados pessoais, URLs privadas ou detalhes que facilitem exploração. Use o botão
**Report a vulnerability** da aba **Security** do repositório no GitHub. Se esse
canal ainda não estiver habilitado, contate o mantenedor por um canal
institucional privado informado nos metadados do repositório.

Inclua, quando possível:

- componente e versão afetados;
- passos mínimos para reproduzir;
- impacto esperado e condições necessárias;
- evidência sanitizada, sem segredos nem dados pessoais;
- sugestão de correção, se houver.

O recebimento será confirmado pelo canal privado. Prazo e divulgação serão
combinados conforme gravidade, reprodutibilidade e disponibilidade acadêmica.

## Segredos e configuração local

- Nunca versione arquivos `.env`, `api_key.txt`, bancos locais, logs ou dumps.
- Gere valores fortes e distintos para todas as variáveis marcadas como
  `CHANGE_ME` nos arquivos `.env.example`.
- Não use chaves de benchmark ou desenvolvimento em uma implantação real.
- Se um segredo aparecer em histórico, log, captura de tela ou mensagem,
  revogue-o e gere outro; apenas apagar o texto não elimina a exposição.
- As interfaces Docker deste projeto são vinculadas a `127.0.0.1`. Exposição
  em outra interface exige autenticação, TLS, firewall e revisão de risco.

## Dados institucionais

Os artefatos identificados no `NOTICE` como internos ou restritos não devem ser
publicados. Antes de compartilhar qualquer dataset, confirme origem, base legal,
anonimização, licença, autorização institucional e ausência de identificadores
diretos ou indiretos.

## Limites do sistema

Classificações e decisões de duplicidade podem estar erradas. Mantenha os
controles humanos e as trilhas de auditoria previstos pelo projeto, sobretudo
antes de ações irreversíveis ou comunicações institucionais sensíveis.
