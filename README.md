# VALLIÈRE Bot — Fase 1

## IA das personagens

O bot usa Groq por padrão. Para testar Gemini sem alterar personagens, memória,
localização ou webhooks, configure as variáveis privadas da hospedagem:

```text
AI_PROVIDER=gemini
GEMINI_API_KEY=<chave criada no Google AI Studio>
GEMINI_MODEL=gemini-2.5-flash-lite
```

Para manter Groq, deixe `AI_PROVIDER=groq` (ou não defina essa variável) e use
`GROQ_API_KEY` e, opcionalmente, `GROQ_MODEL`. Não publique chaves no repositório.
Depois da implantação, rode `/diagnosticoia personagem:olivia-bennett` em um
canal físico com Olivia presente e a cidade acordada. O diagnóstico é privado
para administradores, mas uma resposta bem-sucedida é publicada no canal.
O limite gratuito e a disponibilidade dos modelos dependem do projeto e
devem ser conferidos na conta do provedor antes de escolher a configuração.

Núcleo oficial do simulador social persistente VALLIÈRE.

## O que já existe

- estado global persistente no Supabase: dia narrativo, período, cidade e clima;
- catálogo HUMANOS/IA com bloqueio estrutural para Céline, Emma e Briana;
- leitura automática dos canais do Discord como mapa;
- separação entre canais físicos, digitais e administrativos;
- regra de cômodos: cada canal físico é uma localização independente;
- comandos `/cidadeacorda`, `/avancartempo`, `/cidadedorme` e `/status`;
- comando administrativo `/clima`;
- webhooks com nome/avatar individual para cada pessoa de IA;
- comando administrativo `/testarwebhook`;
- pausa narrativa: locais físicos avisam que estão fechados enquanto a cidade dorme;
- `/status` nunca revela a localização de personagens.

## Proteção das três humanas

`Céline`, `Emma` e `Briana` possuem `actor_kind = HUMANO`. O serviço de webhook
recusa qualquer tentativa de produzir uma mensagem para uma delas. Ao dormir a
cidade, somente pessoas de IA podem ter atividade/localização atualizadas pelo
sistema.

## Etapa manual 1 — Supabase Free

Esta etapa exige a conta da proprietária e não deve ser feita compartilhando chaves.

1. Crie um projeto no Supabase Free.
2. Abra **SQL Editor**.
3. Execute `supabase/migrations/001_phase1.sql`.
4. Copie a URL do projeto e a chave **service_role** para o ambiente privado onde
   o bot será executado. Essa chave nunca deve ser colocada no Discord, GitHub ou
   enviada em conversa.

## Etapa manual 2 — aplicação Discord

1. No Discord Developer Portal, crie a aplicação `VALLIÈRE` e um Bot.
2. Em OAuth2/URL Generator selecione `bot` e `applications.commands`.
3. Permissões mínimas: Ver canais, Enviar mensagens, Incorporar links, Ler histórico
   e **Gerenciar Webhooks**.
4. Convide o bot ao servidor.
5. Guarde o token apenas na variável privada `DISCORD_TOKEN`.

O código não requer o intent privilegiado **Message Content** na Fase 1.

## Configuração local de teste

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m valliere
```

Preencha `.env` localmente. Não envie esse arquivo para ninguém.

## Testes sem credenciais

```bash
python -m unittest discover -s tests -v
python -m compileall -q src
```

## Primeiro teste no Discord

1. Inicie o bot.
2. Confira no log `Mapa sincronizado`.
3. Use `/status`.
4. Use `/cidadeacorda` com uma conta administrativa.
5. Use `/avancartempo`.
6. Em um canal físico, use `/testarwebhook personagem:olivia-bennett`.
7. Use `/cidadedorme` e envie uma mensagem em um local físico para confirmar a pausa.

## Fase 2 — ainda não iniciada

A Fase 2 conectará Groq ao núcleo, com contexto isolado por pessoa de IA. A IA não
será autorizada a publicar diretamente: suas decisões passarão pelas regras de
identidade, localização, conhecimento e proteção das humanas antes de chegar aos
webhooks.
