"""Historical memories from HISTORIA.md, with knowledge scoped per NPC."""

PUBLIC_HISTORY = (
    "Antes do RPG, Céline, Emma e Briana abriram a NYX Agency & Atelier em "
    "Vallière. Emma e Briana são irmãs e moram juntas. A NYX apresentou sua "
    "nova fase em um evento com convidados da cidade. O evento já terminou; "
    "a agência ganhou atenção e contatos nas semanas seguintes. Matteo Ricci "
    "é dono do NOIR. Esse passado não agenda compromissos futuros e não "
    "substitui os acontecimentos registrados durante o jogo."
)

# Only events witnessed by, told to, or involving each person are included.
# Especially: two Camilles, unrelated Bennett surnames, and undefined Laurent ties.
PERSONAL_HISTORY = {
    "vivienne": "Mãe de Céline e Camille, casada com Charles. Jantou com Céline e Nathan; foi à apresentação da NYX, elogiou Céline e conversou com Helena Laurent.",
    "charles": "Pai de Céline e Camille, casado com Vivienne. Falou dos custos da festa no jantar familiar; foi à apresentação da NYX e reconheceu Arthur Laurent de círculos profissionais.",
    "camille": "Irmã mais nova de Céline, diferente de Camille Moreau. Jantou com Nathan e a família; compareceu à apresentação da NYX e conversou com Nathan.",
    "nathan": "Amigo antigo de Céline e conhecido da família dela; não é parente nem funcionário da NYX. Jantou com a família, foi à apresentação da agência e conversou com Céline e Camille.",
    "olivia-bennett": "Foi contratada por Céline após entrevista na NYX; organiza a agenda e trabalha na recepção. Ajudou no evento, recebeu Luca na recepção e soube por Emma que ele foi contratado. Na sexta ficaram pendências para segunda; no sábado Céline perguntou por uma pasta e você respondeu 'Na segunda'. Sua confiança com Céline é profissional e pessoal.",
    "noah-carter": "Diretor de casting da NYX; já discordou de Emma sobre a preparação de uma candidata. Participou do evento e pediu a Luca que evitasse flash junto às modelos. Houve mais procura por casting depois. Na sexta, no escritório de Céline na agência, pediu conversa sobre casting; ela disse 'Segunda'.",
    "camille-moreau": "Cuida das relações públicas da NYX; não é a irmã de Céline. Mostrou à equipe uma publicação local sobre a NYX; coordenou comunicação e imprensa no evento. Na sexta, quis mostrar a Céline questões da imagem da agência; ela respondeu 'Segunda'.",
    "theo-beaumont": "Produtor de moda da NYX; lidou com falta de espaço para tecidos, ajudou na preparação do evento e protegeu peças do atelier. Depois, o trabalho cresceu. Na sexta pediu a Emma decisão sobre uma questão de produção; ela respondeu 'Segunda'.",
    "gabriel-torres": "Segurança da NYX; recebeu Luca para um compromisso com Emma e Briana, coordenou entrada e segurança no evento. Na sexta Olivia lhe disse que Céline se arrependeria de adiar tarefas para segunda. Chegou cedo à entrada no primeiro dia do livro.",
    "matteo-ricci": "Dono do NOIR; conheceu Emma e Briana em uma noite no bar. Compareceu como convidado à apresentação da NYX e teve uma conversa breve e profissional com Céline; isso não criou parceria ou romance.",
    "sofia-bellini": "Bartender no NOIR e colega de Matteo; atendeu Emma e Briana na primeira noite delas ali. Foi convidada à apresentação da NYX, conversou com Emma e Kiara e tem vida própria fora do expediente.",
    "luca-moretti": "Fotógrafo; conheceu Emma e Briana no NOIR, depois as encontrou na NYX, mostrou portfólio e foi contratado para fotografar o evento. Gabriel o recebeu na entrada; durante a apresentação Noah pediu que evitasse flash perto das modelos.",
    "kiara-bennett": "Conhece Emma, Briana, Maya e Ryan; convidou as irmãs para ir ao NOIR. Compareceu à apresentação da NYX, conversou com Sofia e foi reconhecida por Amélie das redes. Seu sobrenome não prova parentesco com Olivia.",
    "maya-collins": "Amiga de Emma e Briana; procurou as irmãs para sair ao NOIR com Kiara e Ryan. Compareceu à apresentação da NYX; tem amizades e rotina fora da agência.",
    "ryan-blake": "Conhece Emma, Briana, Maya e Kiara; sugeriu uma saída ao NOIR, compareceu à apresentação da NYX e mantém vida social própria.",
    "helena-laurent": "Vive com Arthur, Liam e Amélie Laurent. Compareceu à apresentação da NYX, observou o espaço e conversou brevemente com Vivienne. Não foi estabelecido parentesco com Emma ou Briana.",
    "arthur-laurent": "Vive com Helena, Liam e Amélie Laurent. Na apresentação da NYX, reconheceu Charles de círculos profissionais e conversou com ele. Não foi estabelecido parentesco com Emma ou Briana.",
    "liam-laurent": "Vive com Helena, Arthur e Amélie Laurent. Frequentou o NOIR e compareceu à apresentação da NYX, onde conversou perto do bar. Não foi estabelecido parentesco com Emma ou Briana.",
    "amelie-laurent": "Vive com Helena, Arthur e Liam Laurent. Compareceu à apresentação da NYX e reconheceu Kiara das redes sociais. Não foi estabelecido parentesco com Emma ou Briana.",
}


def history_for(character_id: str) -> str:
    """Publicly known events plus experiences specific to this NPC."""
    return PUBLIC_HISTORY + " Passado vivido por você: " + PERSONAL_HISTORY.get(
        character_id, "Nenhum outro acontecimento pessoal definido no livro."
    )
