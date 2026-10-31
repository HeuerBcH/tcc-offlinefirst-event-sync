# tcc-offlinefirst-event-sync

Protótipo do TCC "Sincronização Baseada em Eventos para Aplicações Offline-First".

Implementa o mecanismo de sincronização baseado em eventos (cliente com fila local em SQLite,
servidor com deduplicação, ordem por `seq` e LWW) e o ambiente que o avalia sob condições de rede
emuladas (`tc netem` em containers Docker).

Em construção. Ver `DECISIONS.md` para as decisões de projeto.
