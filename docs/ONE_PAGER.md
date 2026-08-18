# Três alavancas de receita — próximos 6 meses

**Para:** Diretoria Executiva · **De:** Analista PL · 17/08/2026

Base total refere-se a 96.478 pedidos entregues, R$ 13,2M em GMV. As projeções fora feitas sobre **R$ 5,51M**, faturamento do último semestre (2018-S1).

*Racional analítico, memória de cálculo e hipóteses testadas e descartadas em* [`notebooks/analise_alavancas.ipynb`](../notebooks/analise_alavancas.ipynb).

| # | Alavanca | Ganho semestral | % da base | Quando |
|:-:|:---|---:|---:|:---|
| 1 | Parcelamento sem juros em até 10x | +R$ 231k a 347k | +4,2% a 6,3% | Mês 1–2 |
| 2 | Curadoria de sortimento por causa-raiz | +R$ 175k | +3,2% | Mês 2–4 |
| 3 | Ativação de vendedores locais no N/NE | +R$ 123k a 185k | +2,2% a 3,4% | Mês 3–6 |
| | **Total** | **+R$ 530k a 707k** | **+9,6% a 12,8%** | |

### 1. Parcelamento sem juros em até 10x

>**Evidência.** À vista o pedido médio é R$ 95,83; em 10x, R$ 413,69 (4,3 vezes mais). Cartão responde por 78,4% do valor transacionado, e 11.567 pedidos do semestre foram pagos à vista no cartão.

>**Ação.** Subsidiar a taxa de antecipação (~3,5%) em itens acima de R$ 150, priorizando informática, relógios e móveis.

>**Meta.** Ticket médio acima de R$ 160. A relação parcela–valor é observacional: escala condicionada a um A/B de 60 dias.

### 2. Curadoria de sortimento por causa-raiz

>**Evidência.** Três em cada cinco detratores receberam o pedido **no prazo**: 3.494 pedidos, R$ 583k de GMV no semestre. Nenhum indicador operacional explica essa insatisfação; só o NLP sobre o texto das avaliações.

>**Ação.** Painel de causa-raiz por vendedor e remediação de 30 dias para reincidentes. Vitrine só como último recurso.

>**Meta.** Detração em pedidos pontuais abaixo de 6,5%.

### 3. Ativação de vendedores locais no N/NE

>**Evidência.** A região concentram 11,4% dos compradores e apenas 1,97% dos vendedores. Os poucos vendedores locais que já operam entregam bem melhor: frete de R$ 23,90 em 15,3 dias, contra R$ 33,43 em 20,5 dias de quem envia de fora (29% mais barato e 5 dias mais rápido).

>**Ação.** Recrutar 80 a 120 lojistas em Recife, Fortaleza, Salvador, Manaus e Belém, com onboarding assistido.

>**Meta.** GMV por vendedor ativado acima de R$ 3.400 no 90º dia. A meta é ativação, não cadastro: 55% da base vendeu menos de 10 itens em dois anos.

**Premissas.** Dois números são estimativa nossa, não medição: quantos compradores à vista migram para 10x (8% a 12%, na A1) e quanto do GMV exposto conseguimos recuperar (30%, na A2). Escolhemos faixas baixas de propósito, para que o desvio seja para cima.

**Riscos.** Na A1, subsidiar a antecipação consome margem, e por isso a escala só vem depois do A/B. Na A2, cobrar melhora de quem já vende gera atrito, então a remediação vem antes de qualquer restrição de vitrine. Na A3, o lojista recrutado não vender é o risco mais provável dos três, e já está na conta: assumimos que só 45% ativam.
