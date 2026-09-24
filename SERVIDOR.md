# Preparação do servidor VALLIÈRE

Na primeira inicialização após estas mudanças, o bot procura a categoria
`01・START` e cria `#bem-vindos` e `#historia` se ainda não existirem. A história
integral é anexada ao segundo canal e também fica em [HISTORIA.md](HISTORIA.md).
Se o bot tiver a permissão **Gerenciar servidor**, `#bem-vindos` passa a receber
as notificações nativas de novos membros. Para criar canais e publicar o livro,
precisa de **Gerenciar canais**, **Ver canal**, **Enviar mensagens** e
**Anexar arquivos**.

São criadas 14 casas: uma para Vivienne, Charles e Camille; outra para os quatro
Laurent; as outras 12 pertencem a NPCs individualmente. Cada casa tem sala e
quartos. As moradias são registradas no personagem no Supabase sem sobrescrever
localizações já existentes. NPCs podem voltar para casa; só entram na casa de
outra pessoa por convite do morador. Os quartos e casas das jogadoras continuam
sob o controle das humanas.

O bot tenta uma única limpeza de mensagens anteriores a **24/09/2026,
15:55:12 UTC** nos canais físicos e digitais. Mensagens fixadas e os canais
`#bem-vindos` e `#historia` são preservados. Precisa de **Gerenciar mensagens** e
**Ler histórico** nesses canais. Se faltar acesso, a limpeza parcial fica nos
logs e o comando administrativo `/limpartestes modo:prévia` mostra o que ainda
há para limpar. `/limpartestes modo:apagar` conclui a limpeza. Mensagens novas
enviadas depois do horário de corte permanecem.

## Contato por celular

- `/celular personagem:olivia-bennett` inicia uma ligação.
- `/mensagem personagem:noah-carter` inicia uma conversa por texto.
- Ambos aceitam uma primeira fala opcional e depois recebem as próximas falas
  normais no mesmo canal por até dez minutos de inatividade.
- Toda resposta remota mostra 📱 e identifica ligação ou mensagem. O NPC
  permanece onde estava fisicamente.
- `/desligar` encerra o contato. As falas normais posteriores voltam a ser
  interpretadas como conversa no local.

O bot recebe a conversa em canal visível para quem tem acesso ao canal. Para
interpretação privada, use um canal cujas permissões já sejam privadas.
