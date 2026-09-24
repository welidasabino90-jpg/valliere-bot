-- Acrescenta apenas a relação aprovada, preservando outros dados do perfil.
update public.characters
set profile = coalesce(profile, '{}'::jsonb) || jsonb_build_object(
  'relationship_with_celine',
  'Mantém uma relação profissional com Céline, com confiança pessoal no dia a dia. Age com discrição e respeita a autonomia e as decisões de Céline.'
)
where character_id = 'olivia-bennett';
