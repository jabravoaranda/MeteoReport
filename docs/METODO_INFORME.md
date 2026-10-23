# Método de generación y colaboración

## Objetivo

Producir un informe PDF compacto y reproducible de Hoya de Pedraza, para un periodo
elegido por meses completos. El periodo puede abarcar un semestre o un año, pero
los resultados se organizan por mes. Orientación: 8–12 páginas, ajustable al contenido.

La lectura de originales, los cálculos y la composición del documento son fases
separadas. Un cambio de texto, colores o distribución de páginas no debe provocar
una nueva lectura de los instrumentos. Las ejecuciones rutinarias se realizan
localmente desde VS Code, sin llamadas a modelos.

## Contenido acordado

| Sección | Contenido | Tipo de actualización |
|---|---|---|
| Presentación | Estación, objetivo, periodo y perspectiva científica | Texto fijo con periodo y fecha variables |
| Instrumentación | Una ficha breve por instrumento: medida, unidad, productos y límites | Texto fijo, revisado cuando cambia la instrumentación o el método |
| Disponibilidad | Calendario de cobertura y tabla mensual por instrumento | Generada a partir de registros y controles de calidad |
| Resultados | Figuras, tabla breve y comentario de cada instrumento | Cifras y figuras automáticas; interpretación revisada |
| Síntesis | Hallazgos principales y límites del estudio | Texto revisado para el periodo |
| Anexo opcional | Métodos, descartes y procedencia detallada | Generado a partir de metadatos |

No identificar «registros disponibles» con «instrumento funcionando»: los archivos
permiten demostrar disponibilidad y validez según los criterios aplicados, no
necesariamente el estado operativo durante los huecos.

### Fichas de resultados

| Instrumento | Variables y tratamiento | Figuras del cuerpo principal | Tabla breve |
|---|---|---|---|
| Pluviómetro | Diferencias válidas de totalNTR; 7999 como NaN; sin atravesar huecos ni reinicios | Acumulados mensuales e histograma de acumulados diarios completos | Cantidad observada, cobertura, días completos y máximos |
| Parsivel | precipitation, rain_intensity y weather_code_wawa, con los criterios documentados | Acumulados, cajas mensuales de intensidad positiva y tipos de precipitación | Cobertura, n, mediana, P95 y máximo con fecha |
| MRR-PRO | RR, LWC, Ze, VEL y WIDTH; mediana vertical por instante en 640–840 m; mínimo un nivel válido | Una figura por año con cinco paneles y cajas por mes | Cobertura, n, niveles contribuyentes, mediana y percentiles |

Los acumulados incompletos se identifican como cantidades observadas. No se
extrapolan ni se convierten huecos en ceros. Los meses no analizados se distinguen
de los meses analizados sin datos. Las unidades, filtros y escalas de las figuras
se indican expresamente. Los extremos se conservan salvo un criterio de calidad
documentado. RR/LWC se interpretan teniendo en cuenta el procesamiento de fase líquida.

El episodio de precipitación es opcional, como máximo uno, y solo se incorpora
si está seleccionado y sus datos son evaluables. No bloquea el resto del informe.
La banda brillante y nuevos productos requieren una decisión específica antes
de ampliar este contenido.

## Fases de generación

### 1. Definir una edición

Fijar antes de la ejecución:

- Mes inicial y final, ambos incluidos.
- Instrumentos que deben aparecer.
- Rutas de datos preparados y de resultados.
- Método vigente: variables, capa del MRR, filtros, unidades y escalas.

Usar una configuración y un identificador de edición del tipo
`2024-04_2024-09_borrador01`. Registrar la configuración junto al documento.
La configuración de edición del PDF se implementará con el generador; no se
presupone que los analizadores actuales ya entiendan esos campos.

### 2. Preparar datos y resultados numéricos

Esta es la fase de acceso a los originales. Guardar muestras preparadas,
estadísticos, cobertura y procedencia para reutilizarlos. Indicar qué meses
terminaron correctamente y cuáles fallaron. Conservar las lecturas correctas
cuando se reintente un periodo incompleto.

Cambiar el periodo solo añade los meses necesarios. Cambiar de capa o añadir
variables no extraídas puede requerir una preparación nueva. Incorporar originales
modificados requiere volver a comprobarlos. No borrar la caché para cambiar el diseño.

### 3. Generar figuras y componer el documento

Usar únicamente resultados locales preparados. Si falta un producto, identificarlo
como pendiente o no disponible; no iniciar una lectura de red de forma implícita.

La plantilla tendrá textos fijos separados de los contenidos variables:

- Textos fijos: objetivo general, instrumentos y metodología.
- Contenidos variables: periodo, cobertura, figuras, tablas y comentarios.
- Comentarios automáticos: solo hechos verificables, como máximos, fechas o huecos.
- Interpretación científica: texto redactado y revisado, sin inventar causas de los resultados.

El entregable incluirá PDF, fuentes LaTeX, figuras y tablas utilizadas, configuración,
metadatos y un registro de generación. Las referencias de figuras serán relativas
al proyecto LaTeX. Los originales NetCDF/TOA5 no se duplican dentro del documento.
Overleaf será un editor opcional de esas fuentes, no un paso obligatorio.

### 4. Revisar y cerrar una edición

Comprobar periodo, instrumentos, cobertura, unidades, denominadores, identificación
de huecos y coherencia de cifras entre tablas, figuras y comentarios. Revisar el
PDF renderizado: legibilidad, cortes, leyendas, tablas y páginas vacías.

Marcar el documento como borrador hasta la revisión de contenido. Conservar la
edición final identificada y sus insumos; una modificación posterior produce una
nueva revisión. Un cambio editorial solo recompone el documento. Un cambio de
estadísticos recalcula desde las muestras preparadas cuando estas sean suficientes.

## Cómo trabajamos tú y yo

| Momento | Tú | Yo |
|---|---|---|
| Elegir alcance | Indicas periodo, instrumentos y objetivo; puedes mantener los valores ya acordados | Concreto el contenido, señalo datos pendientes y doy la configuración/comando |
| Ejecutar | Lanzas preparación y generación desde VS Code | Mantengo los programas; no sustituyo la ejecución local rutinaria por cálculos en la conversación |
| Resolver errores | Indicas el comando y el mensaje de error, o la ruta del registro | Diagnostico y corrijo; verifico con pruebas pequeñas y caché existente |
| Revisar presentación | Señalas cambios concretos: figura, sección o página | Modifico plantilla, textos o figuras sin releer originales cuando no es necesario |
| Interpretar resultados | Aportas contexto de la estación y decides el enfoque científico | Ayudo a redactar resultados y límites basados en las cifras, diferenciando observación e interpretación |
| Cerrar edición | Revisas el borrador y señalas si queda listo | Dejo PDF, fuentes, configuración y procedencia consistentes |

No necesitas adjuntar otra vez archivos que ya estén accesibles en el repositorio:
basta con indicar su ruta. Para ahorrar trabajo, agrupa correcciones de una revisión
en un solo mensaje. Ejemplo: «Revisa el borrador del semestre; reduce la introducción,
aumenta el tamaño de las cajas del MRR y añade el porcentaje de cobertura en la tabla».

Las preguntas se reservan para decisiones científicas, cambios de alcance o datos
que no podamos deducir del proyecto. Las decisiones ya acordadas se conservan;
no hace falta aprobar de nuevo cada paso técnico ni cada ejecución previamente autorizada.

## Estado real del repositorio

| Elemento | Estado |
|---|---|
| Entorno uv, lanzador por mes/periodo y tareas de VS Code | Disponible |
| Informes HTML, CSV y figuras de instrumentos | Disponible |
| MRR-PRO: preparación persistente y figuras sin consultar originales | Disponible |
| MRR-PRO: figura anual con todas las cajas de varios meses | Pendiente; el piloto actual muestra un mes y los otros quedan grises |
| Preparación persistente independiente para superficie/Parsivel | Pendiente; los analizadores actuales leen sus TOA5 al ejecutarse |
| Calendario y tabla común de disponibilidad | Disponible a partir de los CSV mensuales; no consulta originales |
| Plantilla LaTeX, composición automática y exportación a PDF | Pendiente de implementación |

Primera implementación del PDF: una edición de muestra con resultados ya generados,
para comprobar estructura y presentación. Después se conectará la plantilla al
periodo completo y se completarán los productos pendientes necesarios. No se
procesa toda la base de datos para diseñar la plantilla.
