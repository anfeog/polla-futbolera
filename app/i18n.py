"""
Sistema de idiomas: español (por defecto), portugués e inglés.

Uso en plantillas:  {{ t('Texto en español') }}
- La clave ES el texto en español (si falta traducción, se muestra tal cual).
- El idioma activo viene de la cookie "lang" (middleware en main.py).
"""
from contextvars import ContextVar

current_lang: ContextVar[str] = ContextVar("current_lang", default="es")

LANGS = {"es": "Español", "pt": "Português", "en": "English"}
LANG_FLAGS = {"es": "🇪🇸", "pt": "🇧🇷", "en": "🇬🇧"}

# clave (español) -> (portugués, inglés)
STRINGS = {
    # ── Navegación ──────────────────────────────────────────────
    "Inicio": ("Início", "Home"),
    "Partidos": ("Jogos", "Matches"),
    "Cuadro": ("Chaves", "Bracket"),
    "Calendario": ("Calendário", "Calendar"),
    "CALENDARIO": ("CALENDÁRIO", "CALENDAR"),
    "local": ("local", "local"),
    "Todos los partidos por fecha, en tu hora local. Cierre 1 min antes de cada partido.":
        ("Todos os jogos por data, no seu horário local. Fecha 1 min antes de cada jogo.",
         "All matches by date, in your local time. Closes 1 min before each match."),
    "Pronosticado": ("Palpitado", "Predicted"),
    "Pendiente": ("Pendente", "Pending"),
    "Cerrado": ("Encerrado", "Closed"),
    "No hay partidos cargados": ("Não há jogos carregados", "No matches loaded"),
    "Predecir": ("Palpitar", "Predict"),
    "Goles": ("Gols", "Goals"),
    "Premios": ("Prêmios", "Awards"),
    "PARTIDOS": ("JOGOS", "MATCHES"),
    "Elige una fase para ver y pronosticar sus partidos.":
        ("Escolha uma fase para ver e palpitar seus jogos.",
         "Pick a stage to view and predict its matches."),
    "Equipos por definir": ("Times a definir", "Teams TBD"),
    "de": ("de", "of"),
    "pronosticados": ("palpitados", "predicted"),
    "Completado ✓": ("Completo ✓", "Completed ✓"),
    "Se habilita al definirse los clasificados": ("Habilita quando os classificados forem definidos", "Unlocks once qualifiers are set"),
    "Ver cuadro →": ("Ver chaves →", "View bracket →"),
    "Aún no cargados": ("Ainda não carregados", "Not loaded yet"),
    "Tabla": ("Tabela", "Table"),
    "El cuadro": ("As chaves", "The bracket"),
    "Ver completo →": ("Ver completo →", "View full →"),
    "Provisional": ("Provisório", "Provisional"),
    "Dieciseisavos proyectados con las posiciones actuales. Se actualizan con los cruces reales cuando terminen los grupos.":
        ("Trinta e dois projetados com as posições atuais. Atualizam-se com os confrontos reais quando os grupos terminarem.",
         "Round of 32 projected from current standings. Updates with the real matchups once the groups finish."),
    "Mejores terceros": ("Melhores terceiros", "Best third-placed"),
    "Ver grupos →": ("Ver grupos →", "View groups →"),
    "Equipo": ("Time", "Team"),
    "Los": ("Os", "The"),
    "mejores avanzan a la siguiente ronda": ("melhores avançam à próxima fase", "best advance to the next round"),
    "Goleadores": ("Artilheiros", "Top scorers"),
    "Cómo jugar": ("Como jogar", "How to play"),
    "Salir": ("Sair", "Exit"),
    "Cerrar sesión": ("Encerrar sessão", "Log out"),
    "Mi perfil": ("Meu perfil", "My profile"),
    "Perfil": ("Perfil", "Profile"),

    # ── Login ───────────────────────────────────────────────────
    "Usuario": ("Usuário", "Username"),
    "Contraseña": ("Senha", "Password"),
    "Entrar a la cancha": ("Entrar em campo", "Enter the pitch"),
    "Usuario o contraseña incorrectos": ("Usuário ou senha incorretos", "Incorrect username or password"),
    "Idioma": ("Idioma", "Language"),

    # ── Inicio ──────────────────────────────────────────────────
    "¡HOLA,": ("OLÁ,", "HEY,"),
    "Bienvenido a la Polla Futbolera del Mundial 2026. Predice los marcadores, adivina los goleadores y compite con tus amigos.":
        ("Bem-vindo ao Bolão da Copa 2026. Preveja os placares, adivinhe os artilheiros e dispute com seus amigos.",
         "Welcome to the 2026 World Cup pool. Predict scores, guess the scorers and compete with your friends."),
    "Ver tutorial": ("Ver tutorial", "View tutorial"),
    "Todos los partidos": ("Todos os jogos", "All matches"),
    "Te falta pronosticar": ("Falta você palpitar", "Still to predict"),
    "Cierre 1 min antes del pitido": ("Fecha 1 min antes do apito", "Closes 1 min before kickoff"),
    "¡Estás al día!": ("Você está em dia!", "You're all caught up!"),
    "Ya pronosticaste todos los próximos partidos. Vuelve cuando se acerquen nuevos.":
        ("Você já palpitou em todos os próximos jogos. Volte quando houver novos.",
         "You've predicted all upcoming matches. Come back when new ones approach."),
    "Ver la tabla →": ("Ver a tabela →", "See the table →"),
    "No hay partidos próximos cargados todavía.": ("Ainda não há jogos carregados.", "No upcoming matches loaded yet."),
    "Pronosticar →": ("Palpitar →", "Predict →"),
    "Sin pronóstico": ("Sem palpite", "No prediction"),
    "🔒 Pronósticos cerrados": ("🔒 Palpites encerrados", "🔒 Predictions closed"),
    "Te faltan los premios": ("Faltam os prêmios", "Awards still pending"),
    "Bota de Oro, campeón, total de goles… ciérralos antes de que empiece el Mundial.":
        ("Chuteira de Ouro, campeão, total de gols… feche antes do início da Copa.",
         "Golden Boot, champion, total goals… lock them in before the World Cup starts."),
    "Predecir →": ("Palpitar →", "Predict →"),
    "Aún tienes tu comodín x2": ("Você ainda tem seu coringa x2", "You still have your x2 wildcard"),
    "Sin usar en:": ("Sem usar em:", "Unused in:"),
    "Actívalo al pronosticar un partido para duplicar sus puntos.":
        ("Ative ao palpitar um jogo para dobrar os pontos.",
         "Activate it when predicting a match to double its points."),
    "Cierra en": ("Fecha em", "Closes in"),
    "Dom,Lun,Mar,Mié,Jue,Vie,Sáb": ("Dom,Seg,Ter,Qua,Qui,Sex,Sáb", "Sun,Mon,Tue,Wed,Thu,Fri,Sat"),
    "Ene,Feb,Mar,Abr,May,Jun,Jul,Ago,Sep,Oct,Nov,Dic":
        ("Jan,Fev,Mar,Abr,Mai,Jun,Jul,Ago,Set,Out,Nov,Dez",
         "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec"),

    # ── Fases (labels de STAGE_LABELS) ──────────────────────────
    "Fase de Grupos": ("Fase de Grupos", "Group Stage"),
    "Dieciseisavos": ("Dezesseis avos", "Round of 32"),
    "Octavos de Final": ("Oitavas de final", "Round of 16"),
    "Cuartos de Final": ("Quartas de final", "Quarter-finals"),
    "Semifinales": ("Semifinais", "Semi-finals"),
    "Tercer Puesto": ("Terceiro lugar", "Third place"),
    "Final": ("Final", "Final"),

    # ── Tabla / ranking ─────────────────────────────────────────
    "Clasificación general": ("Classificação geral", "Overall ranking"),
    "TABLA": ("TABELA", "TABLE"),
    "Aún no hay puntos acumulados": ("Ainda não há pontos acumulados", "No points accumulated yet"),
    "puntos": ("pontos", "points"),
    "puntos provisionales": ("pontos provisórios", "provisional points"),
    "Jugador": ("Jogador", "Player"),
    "(tú)": ("(você)", "(you)"),
    "MA = Marcador exacto +3": ("MA = Placar exato +3", "MA = Exact score +3"),
    "GAN = Ganador +1": ("GAN = Vencedor +1", "GAN = Winner +1"),
    "GOL = Goleador en orden +2": ("GOL = Artilheiro na ordem +2", "GOL = Scorer in order +2"),
    "Autogol +20": ("Gol contra +20", "Own goal +20"),
    "Premio +10": ("Prêmio +10", "Award +10"),
    "Premio bonus": ("Prêmio bônus", "Bonus award"),
    "Comodín x2": ("Coringa x2", "Wildcard x2"),
    "Solo tú lo clavaste +3": ("Só você cravou +3", "Only you nailed it +3"),
    "Solo tú": ("Só você", "Only you"),
    "Tu estado del podio": ("Seu status do pódio", "Your podium status"),
    "Pica a tus rivales con una frase corta. Aparece en tu viñeta encima del podio.":
        ("Provoque seus rivais com uma frase curta. Aparece no seu balão sobre o pódio.",
         "Tease your rivals with a short line. It shows in your bubble above the podium."),
    "Cancelar": ("Cancelar", "Cancel"),
    "Guardar": ("Salvar", "Save"),
    "💬 Poner estado": ("💬 Definir status", "💬 Set status"),

    # ── Goleadores ──────────────────────────────────────────────
    "goles totales": ("gols totais", "total goals"),
    "por partido": ("por jogo", "per match"),
    "El torneo aún no ha comenzado": ("O torneio ainda não começou", "The tournament hasn't started yet"),
    "Los goleadores aparecerán aquí una vez se disputen los primeros partidos":
        ("Os artilheiros aparecerão aqui assim que os primeiros jogos forem disputados",
         "Scorers will appear here once the first matches are played"),
    "Clasificación completa": ("Classificação completa", "Full standings"),
    "Empate → menos partidos jugados": ("Empate → menos jogos disputados", "Tie → fewest matches played"),
    "Selección": ("Seleção", "Team"),
    "Goles": ("Gols", "Goals"),
    "PJ": ("PJ", "MP"),
    "⚡ Desempate: a igual número de goles, va primero quien los marcó en menos partidos":
        ("⚡ Critério de desempate: com gols iguais, vai primeiro quem marcou em menos jogos",
         "⚡ Tiebreaker: same goals → fewest matches played wins"),
    "Autogoles": ("Gols contra", "Own goals"),
    "AG": ("GC", "OG"),

    # ── Partidos (fixture) ────────────────────────────────────────
    "← Todas las fases": ("← Todas as fases", "← All stages"),
    "Cuadro →": ("Chaves →", "Bracket →"),
    "Aún no hay partidos cargados": ("Ainda não há jogos carregados", "No matches loaded yet"),
    "pendiente": ("pendente", "pending"),
    "pendientes": ("pendentes", "pending"),
    "En vivo": ("Ao vivo", "Live"),
    "Tu pronóstico": ("Seu palpite", "Your prediction"),
    "editar": ("editar", "edit"),
    "ver": ("ver", "view"),
    "Resultado real": ("Placar real", "Actual result"),
    "Marcador en vivo": ("Placar ao vivo", "Live score"),
    "En juego — los aciertos se confirman al terminar":
        ("Em andamento — os acertos se confirmam ao terminar",
         "In progress — hits are confirmed when it ends"),
    "Tu marcador": ("Seu placar", "Your score"),
    "No acertaste el resultado": ("Você não acertou o placar", "You missed the result"),
    "No pronosticaste este partido": ("Você não palpitou neste jogo", "You didn't predict this match"),
    "Tus goleadores": ("Seus artilheiros", "Your scorers"),
    "Goleadores reales": ("Artilheiros reais", "Actual scorers"),
    "Lo que pronosticaron todos": ("O que todos palpitaram", "What everyone predicted"),
    "verde = acertado": ("verde = acertou", "green = correct"),
    "Puntos de este partido": ("Pontos deste jogo", "Points from this match"),
    "El partido aún no se juega — aquí verás tus aciertos cuando termine":
        ("O jogo ainda não foi disputado — aqui você verá seus acertos quando terminar",
         "The match hasn't been played yet — you'll see your hits here when it ends"),
    "cerrado": ("encerrado", "closed"),
    "Pronóstico cerrado": ("Palpite encerrado", "Prediction closed"),
    "Pronosticar": ("Palpitar", "Predict"),
    "UTC": ("UTC", "UTC"),
    "Cuadro": ("Chaves", "Bracket"),

    # ── Cuadro eliminatorio ───────────────────────────────────────
    "Bracket completo · mitad izquierda y mitad derecha se encuentran en la Final.":
        ("Chaves completas · metade esquerda e metade direita se encontram na Final.",
         "Full bracket · left half and right half meet in the Final."),
    "Por definir": ("A definir", "TBD"),
    "Por disputar": ("A disputar", "TBD"),
    "3er puesto": ("3º lugar", "3rd place"),
    "Octavos": ("Oitavas", "R16"),
    "Cuartos": ("Quartas", "QF"),
    "Semis": ("Semis", "SF"),

    # ── Gráficas ────────────────────────────────────────────────
    "📈 Evolución de puntos": ("📈 Evolução de pontos", "📈 Points over time"),
    "Puntos acumulados por día": ("Pontos acumulados por dia", "Cumulative points per day"),
    "🧩 ¿De dónde salen los puntos?": ("🧩 De onde vêm os pontos?", "🧩 Where do points come from?"),
    "Top 5 · desglose por tipo de acierto": ("Top 5 · por tipo de acerto", "Top 5 · breakdown by hit type"),
    "🎯 Francotiradores": ("🎯 Franco-atiradores", "🎯 Sharpshooters"),
    "Quién clava más marcadores exactos (+3)": ("Quem crava mais placares exatos (+3)", "Who nails the most exact scores (+3)"),
    "🔮💥 Bola de Cristal Rota": ("🔮💥 Bola de Cristal Quebrada", "🔮💥 Broken Crystal Ball"),
    "Los que peor predicen — menos puntos pese a jugar":
        ("Os piores palpiteiros — menos pontos mesmo jogando",
         "The worst predictors — fewest points despite playing"),
    "Marcador exacto": ("Placar exato", "Exact score"),
    "Ganador": ("Vencedor", "Winner"),
    "Penales": ("Pênaltis", "Penalties"),

    # ── Perfil ──────────────────────────────────────────────────
    "Tu identidad": ("Sua identidade", "Your identity"),
    "MI PERFIL": ("MEU PERFIL", "MY PROFILE"),
    "Así te ven los demás en la tabla.": ("É assim que os outros te veem na tabela.", "This is how others see you in the table."),
    "Elige tu avatar": ("Escolha seu avatar", "Choose your avatar"),
    "Toca un emoji para guardarlo al instante.": ("Toque em um emoji para salvar na hora.", "Tap an emoji to save it instantly."),
    "Cambiar contraseña": ("Alterar senha", "Change password"),
    "Si quieres, cambia la clave que te dieron por una tuya. Es privada, nadie más la ve.":
        ("Se quiser, troque a senha que te deram por uma sua. É privada, ninguém mais a vê.",
         "If you want, replace the password you were given with your own. It's private, nobody else sees it."),
    "Contraseña actual": ("Senha atual", "Current password"),
    "Nueva contraseña": ("Nova senha", "New password"),
    "Repite la nueva contraseña": ("Repita a nova senha", "Repeat the new password"),
    "Actualizar contraseña": ("Atualizar senha", "Update password"),
    "✅ Contraseña actualizada correctamente.": ("✅ Senha atualizada com sucesso.", "✅ Password updated successfully."),
    "La contraseña actual no es correcta.": ("A senha atual não está correta.", "The current password is incorrect."),
    "La nueva contraseña debe tener al menos 4 caracteres.": ("A nova senha deve ter pelo menos 4 caracteres.", "The new password must be at least 4 characters long."),
    "Las dos contraseñas nuevas no coinciden.": ("As duas senhas novas não coincidem.", "The new passwords don't match."),
    "Elige el idioma de la app.": ("Escolha o idioma do app.", "Choose the app language."),

    # ── Premios (versiones cortas para la tabla de otros) ────────
    "Bota de Oro":   ("Chuteira de Ouro", "Golden Boot"),
    "Balón de Oro":  ("Bola de Ouro",     "Golden Ball"),
    "Guante de Oro": ("Luva de Ouro",     "Golden Glove"),
    "Campeón":       ("Campeão",          "Champion"),
    "Subcampeón":    ("Vice-campeão",     "Runner-up"),
    "Total goles":   ("Total de gols",    "Total goals"),
    "Sin pronóstico": ("Sem palpite",     "No prediction"),

    # ── Premios ─────────────────────────────────────────────────
    "Predicciones especiales": ("Palpites especiais", "Special predictions"),
    "PREMIOS": ("PRÊMIOS", "AWARDS"),
    "Predice los grandes premios del torneo. Cada acierto vale": ("Preveja os grandes prêmios do torneio. Cada acerto vale", "Predict the tournament's big awards. Each hit is worth"),
    "+10 puntos": ("+10 pontos", "+10 points"),
    "Autogol acertado =": ("Gol contra acertado =", "Own goal hit ="),
    "+20 puntos": ("+20 pontos", "+20 points"),
    "🔒 Los premios ya están cerrados.": ("🔒 Os prêmios já estão fechados.", "🔒 Awards are now closed."),
    "🥇 Bota de Oro": ("🥇 Chuteira de Ouro", "🥇 Golden Boot"),
    "Máximo goleador del torneo": ("Artilheiro do torneio", "Tournament top scorer"),
    "🏆 Balón de Oro": ("🏆 Bola de Ouro", "🏆 Golden Ball"),
    "Mejor jugador del Mundial": ("Melhor jogador da Copa", "Best player of the World Cup"),
    "🧤 Guante de Oro": ("🧤 Luva de Ouro", "🧤 Golden Glove"),
    "Mejor arquero del torneo": ("Melhor goleiro do torneio", "Best goalkeeper of the tournament"),
    "Ganó:": ("Ganhou:", "Won:"),
    "Fue:": ("Foi:", "It was:"),
    "Fueron:": ("Foram:", "They were:"),
    "Nombre del jugador": ("Nome do jogador", "Player name"),
    "Nombre de la selección": ("Nome da seleção", "Team name"),
    "❓ Preguntas bonus": ("❓ Perguntas bônus", "❓ Bonus questions"),
    "🏆 Campeón del Mundial": ("🏆 Campeão da Copa", "🏆 World Cup champion"),
    "¿Quién levanta la copa?": ("Quem levanta a taça?", "Who lifts the trophy?"),
    "🥈 Subcampeón": ("🥈 Vice-campeão", "🥈 Runner-up"),
    "El finalista que pierde": ("O finalista que perde", "The losing finalist"),
    "🥅 ¿La final se decide por penales?": ("🥅 A final vai aos pênaltis?", "🥅 Will the final go to penalties?"),
    "Arriésgate con un sí o un no": ("Arrisque um sim ou um não", "Take a guess: yes or no"),
    "Sí 🎯": ("Sim 🎯", "Yes 🎯"),
    "No 🛡️": ("Não 🛡️", "No 🛡️"),
    "⚽ Total de goles del Mundial": ("⚽ Total de gols da Copa", "⚽ Total World Cup goals"),
    "¿Cuántos goles se marcarán en todo el torneo? Exacto": ("Quantos gols serão marcados no torneio todo? Exato", "How many goals in the whole tournament? Exact"),
    "si nadie acierta, el más cercano": ("se ninguém acertar, o mais próximo", "if nobody hits it, the closest"),
    "Dato: en Qatar 2022 se marcaron 172 goles": ("Curiosidade: no Catar 2022 foram 172 gols", "Fun fact: Qatar 2022 had 172 goals"),
    "Guardar premios": ("Salvar prêmios", "Save awards"),

    # ── Formulario de predicción ────────────────────────────────
    "← Volver al fixture": ("← Voltar aos jogos", "← Back to fixtures"),
    "Guardar pronóstico": ("Salvar palpite", "Save prediction"),
    "(opcional)": ("(opcional)", "(optional)"),
    "Un casillero por gol,": ("Uma casa por gol,", "One slot per goal,"),
    "en orden": ("em ordem", "in order"),
    "Pon al menos un gol para añadir goleadores.": ("Coloque pelo menos um gol para adicionar artilheiros.", "Add at least one goal to pick scorers."),
    "Acierta el jugador en la posición correcta =": ("Acerte o jogador na posição certa =", "Hit the player in the right spot ="),
    "Marca": ("Marque", "Tick"),
    "si crees que será autogol =": ("se você acha que será gol contra =", "if you think it'll be an own goal ="),
    "— Elegir jugador —": ("— Escolher jogador —", "— Pick a player —"),
    "Gol": ("Gol", "Goal"),
    "🃏 Usar comodín": ("🃏 Usar coringa", "🃏 Use wildcard"),
    "ya usado en esta fase": ("já usado nesta fase", "already used in this stage"),
    "Lo usaste en": ("Você o usou em", "You used it on"),
    "y ese partido ya cerró, así que no se puede mover.":
        ("e esse jogo já fechou, então não pode ser movido.",
         "and that match is closed, so it can't be moved."),
    "(x2 puntos)": ("(x2 pontos)", "(x2 points)"),
    "Duplica todos tus puntos de este partido. Solo": ("Dobra todos os seus pontos deste jogo. Apenas", "Doubles all your points for this match. Only"),
    "uno por fase": ("um por fase", "one per stage"),
    "Prórroga · Penales": ("Prorrogação · Pênaltis", "Extra time · Penalties"),
    "+1 pt quién pasa · +2 pts marcador exacto": ("+1 pt quem passa · +2 pts placar exato", "+1 pt who advances · +2 pts exact score"),
    "Pronóstico de empate detectado — indica quién avanza y el resultado en penales.":
        ("Palpite de empate detectado — indique quem avança e o placar dos pênaltis.",
         "Draw predicted — pick who advances and the shootout score."),
    "¿Quién avanza?": ("Quem avança?", "Who advances?"),
    "Marcador en penales": ("Placar dos pênaltis", "Penalty shootout score"),
    "Los penales no pueden empatar entre sí": ("Os pênaltis não podem empatar", "Penalties can't end level"),
    "Lo que pronostican los demás": ("O que os outros palpitaram", "What the others predicted"),
    "Sé el primero en pronosticar": ("Seja o primeiro a palpitar", "Be the first to predict"),
    "Sin goleadores": ("Sem artilheiros", "No scorers"),
    "pronóstico(s)": ("palpite(s)", "prediction(s)"),
    "Pasa": ("Passa", "Advances"),
    "EN VIVO": ("AO VIVO", "LIVE"),
    "Finalizado": ("Encerrado", "Finished"),
    # ── Easter egg: llamada entrante (Paraguay vs Francia) ──────
    "Te están llamando…": ("Estão te ligando…", "You're getting a call…"),
    "Toca para contestar": ("Toque para atender", "Tap to answer"),
    "⚠️ Ojo: si contestas tu pronóstico de Paraguay vs Francia queda automáticamente 1-0 Paraguay. Si rechazas, queda 0-1 Francia. Se guarda de una — piénsalo bien.":
        ("⚠️ Atenção: se você atender, seu palpite de Paraguai x França fica automaticamente 1-0 Paraguai. Se recusar, fica 0-1 França. Salva na hora — pense bem antes.",
         "⚠️ Heads up: if you answer, your Paraguay vs France prediction automatically becomes 1-0 Paraguay. If you reject, it becomes 0-1 France. It saves instantly — think it through."),
    "Rechazar": ("Recusar", "Reject"),
    "Contestar": ("Atender", "Answer"),
    "Los pronósticos de este partido ya cerraron.": ("Os palpites desse jogo já fecharam.", "Predictions for this match already closed."),
    "Cerrar": ("Fechar", "Close"),
    "a favor de Paraguay": ("a favor do Paraguai", "for Paraguay"),
    "a favor de Francia": ("a favor da França", "for France"),
    "¿Seguro? Tu pronóstico de Paraguay vs Francia va a quedar":
        ("Tem certeza? Seu palpite de Paraguai x França vai ficar",
         "Are you sure? Your Paraguay vs France prediction will become"),
    "Esto reemplaza cualquier pronóstico que ya hayas puesto para ese partido.":
        ("Isso substitui qualquer palpite que você já tenha feito para esse jogo.",
         "This replaces any prediction you've already made for that match."),
    "Listo — tu pronóstico quedó": ("Pronto — seu palpite ficou", "Done — your prediction is now"),
    "No se pudo guardar el pronóstico (¿ya cerró el partido?).":
        ("Não foi possível salvar o palpite (o jogo já fechou?).",
         "Couldn't save the prediction (did the match already close?)."),
    "No se pudo guardar el pronóstico por un error de conexión.":
        ("Não foi possível salvar o palpite por um erro de conexão.",
         "Couldn't save the prediction due to a connection error."),
    # ── Easter egg: meme Vini/Haaland (Brazil vs Norway) ────────
    "Vini y Haaland te mandaron algo…": ("Vini e Haaland te mandaram uma coisa…", "Vini and Haaland sent you something…"),
    "Toca para verlo": ("Toque para ver", "Tap to watch"),
}


def t(text: str) -> str:
    """Traduce el texto según el idioma activo (cookie). Fallback: español."""
    lang = current_lang.get()
    if lang == "es":
        return text
    pair = STRINGS.get(text)
    if not pair:
        return text
    return pair[0] if lang == "pt" else pair[1]


def get_lang() -> str:
    return current_lang.get()
