# MeteoReport · Hoya de Pedraza

Programa Python para obtener resúmenes estadísticos de los instrumentos almacenados
en `Z:\HDP`. Lee los originales y escribe los resultados en una carpeta local.

El [método de generación del PDF y de colaboración](docs/METODO_INFORME.md)
establece contenido, fases, responsabilidades y funcionalidades pendientes.
La exportación automática a PDF todavía no está implementada.

## Ejecutar desde VS Code

1. Abre esta carpeta en VS Code. Instala las extensiones Python y Python Debugger
   si VS Code muestra las recomendaciones del repositorio.
2. La primera vez, ejecuta `uv sync --locked --managed-python` en la terminal,
   o la tarea **MeteoReport: preparar entorno**.
3. Pulsa **Ctrl+Shift+B**, elige instrumento y escribe el mes (`AAAA-MM`).
4. El proceso se ejecuta en la terminal y abre el informe al terminar.
   Los resultados quedan en `informes/<instrumento>/<AAAA-MM>/`.

También puedes usar **Terminal > Run Task**:

| Tarea | Acción |
|---|---|
| Ejecutar informe mensual | Pregunta instrumento y mes; calcula y abre el informe |
| Ejecutar config.toml | Usa el mes guardado en la configuración |
| Comprobar parámetros sin calcular | Muestra comando y salida prevista; no lee datos |
| Pruebas | Ejecuta las pruebas automáticas con datos sintéticos |

Edita **[config.toml](config.toml)** para cambiar la ruta de los datos, el mes por
defecto, la carpeta de resultados, el intervalo vertical del MRR-PRO o sus procesos
de lectura. **F5** permite depurar el mes de esa configuración, incluidos los
subprocesos. Puedes cancelar una tarea desde la papelera de su terminal o con
`Ctrl+C`.

Desde la terminal, sin activar manualmente el entorno:

```powershell
uv run --locked python run_report.py meteo --month 2024-01 --open
uv run --locked python run_report.py disdrometer --month 2024-01 --open
uv run --locked python run_report.py mrrpro --month 2024-03 --open
```

Para revisar los parámetros sin cálculos:

```powershell
uv run --locked python run_report.py mrrpro --month 2024-03 --dry-run
```

Por defecto se procesa un mes; también se puede seleccionar un rango como se
explica a continuación. Repetir instrumento y mes actualiza su misma
carpeta de informe. La caché del MRR-PRO se comparte en `informes/cache/mrrpro/`,
independientemente de la carpeta del informe, y evita releer los NetCDF que no han
cambiado. Cambiar la capa, los archivos o el número de procesos puede requerir
una lectura nueva. No hace falta abrir una conversación ni usar un modelo para
ejecutar estas tareas locales.

### Ejecutar varios meses

```powershell
uv run --locked python run_report.py mrrpro --from-month 2024-03 --to-month 2024-05 --open
```

Ambos límites están incluidos. El lanzador ejecuta cada mes de forma secuencial,
reutiliza la caché y genera un índice con enlaces y estados, abriendo una sola
página al finalizar. Conserva un informe independiente por mes; el periodo no
fusiona todavía las cajas mensuales en una única figura anual.

Por defecto se detiene si un mes falla. Añade `--continue-on-error` si quieres
que siga con los siguientes, por ejemplo cuando hay meses sin datos. El índice
marca los errores y el comando devuelve un estado de error si alguno falló.
`--dry-run` también funciona para rangos y permite revisar todos los comandos
sin iniciar cálculos ni crear informes.

En VS Code, usa **Terminal > Run Task > MeteoReport: ejecutar periodo**. Esta tarea
pregunta los meses inicial y final y continúa si falla algún mes.

### MRR-PRO: separar lectura y figuras

La parte lenta es abrir los NetCDF originales en la unidad de red. Puedes hacerla
una vez y guardar fechas y las cinco variables de todos los niveles de la capa:

```powershell
uv run --locked python run_report.py mrrpro --from-month 2024-03 --to-month 2024-05 --prepare-only
```

Después, para generar o cambiar las figuras sin volver a consultar los originales:

```powershell
uv run --locked python run_report.py mrrpro --from-month 2024-03 --to-month 2024-05 --figures-only --open
```

También funciona con `--month`. Sin una opción de fase, se preparan datos y se
generan figuras seguidas, como antes. Las dos fases tienen tareas específicas en
VS Code, con nombres **MRR-PRO: preparar datos del periodo (sin figuras)** y
**MRR-PRO: figuras del periodo (sin leer originales)**.

Los archivos locales `informes/cache/mrrpro/prepared_*.npz` conservan las muestras,
no solo sus promedios: permiten recalcular percentiles, filtros y presentación.
La fase de figuras no comprueba la unidad de red y puede ejecutarse sin acceso a
ella, conservando la misma ruta de origen en config.toml para identificar los datos.
Si falta un mes preparado, informa del error y no intenta leer los originales.
Cambiar la capa o añadir variables no extraídas requiere una nueva preparación.
Para incorporar nuevos originales o cambios en ellos, vuelve a ejecutar la fase
de preparación. No borres `informes/cache/` si quieres conservar estas lecturas.

El alcance del estudio es **mensual**, sin análisis anual ni estacional, y como
máximo un evento destacado. Se propone seleccionar la ventana móvil de 72 horas
con mayor precipitación que alcance **50 mm (50 l/m²)**. Es un criterio del
proyecto, configurable, no un umbral oficial de aviso meteorológico. Si no se
puede evaluar o ninguna ventana alcanza el umbral, no se incluye un evento.

La tabla mensual de superficie incluye meses sin datos, identificados con cobertura
cero y estadísticos ausentes. La cobertura usa el mes natural completo, incluso
si el filtro de fechas selecciona solo una parte. Las frecuencias de códigos y
el CSV de resumen general corresponden al periodo seleccionado. El radar se mantiene
como herramienta complementaria para examinar el intervalo de un eventual evento;
no se procesa automáticamente todo su archivo para el informe mensual.

## Instalación

El proyecto usa **uv y Python 3.12**, con un entorno `.venv` aislado. En PowerShell,
desde este repositorio:

```powershell
uv sync --locked --managed-python
```

`uv` instala Python si hace falta. Si no está instalado, sigue la
[guía oficial de instalación](https://docs.astral.sh/uv/getting-started/installation/).
El entorno no depende del runtime de ninguna aplicación. `pyproject.toml` define
las dependencias y `uv.lock` fija sus versiones; ambos se guardan en Git.
`requirements.txt` es una exportación de compatibilidad, no la fuente de edición.

Para añadir una dependencia: `uv add NOMBRE`. Para actualizar una concreta:
`uv lock --upgrade-package NOMBRE` y `uv sync --locked`. Para regenerar la exportación:

```powershell
uv export --locked --format requirements-txt --no-hashes --no-emit-project --output-file requirements.txt
```

## Uso directo de los analizadores (opcional)

Superficie (ambos archivos TOA5 completos):

```powershell
.\.venv\Scripts\python.exe meteoreport.py
Invoke-Item .\informes\ultimo\informe.html
```

Periodo concreto (inicio incluido, fin excluido):

```powershell
.\.venv\Scripts\python.exe meteoreport.py --instrument meteo --start 2024-01-01 --end 2024-02-01 --output informes/enero2024
```

Radar, en UTC:

```powershell
.\.venv\Scripts\python.exe meteoreport.py --instrument radar --start 2026-06-01 --end 2026-06-02 --output informes/radar20260601
```

Disdrómetro, con acumulados, boxplots y tipos de precipitación:

```powershell
.\.venv\Scripts\python.exe meteoreport.py --instrument disdrometer --output informes/disdrometro
```

Prueba mensual del MRR-PRO a un nivel fijo (sin procesar el archivo completo):

```powershell
.\.venv\Scripts\python.exe mrrpro.py --month 2024-03 --layer 640 840 --output informes/mrrpro_prueba
```

El piloto presenta una figura del año con cinco paneles (`RR`, `LWC`, `Ze`, `VEL`,
`WIDTH`). Primero calcula la **mediana vertical por instante entre 640 y 840 m**
sobre el instrumento; después construye la distribución mensual de esas medianas.
En la malla revisada se utilizan 640, 675, 710, 745, 780 y 815 m; no se interpola a
840 m ni se incluye el nivel 850 m. Cada mediana requiere al menos una celda válida,
y la tabla indica cuántos niveles contribuyen. `--height` permite estudiar un nivel
exacto por separado. Solo el mes solicitado está analizado; los demás se marcan en gris.
Exporta una tabla mensual, una comprobación separada de los niveles 640/675 m y
los metadatos de procedencia. Nunca sustituye automáticamente el nivel solicitado.
Exige orientación vertical y un nivel `range` exacto, sin interpolar.
La carga se guarda en caché local por mes, niveles, ruta, tamaño y fecha de modificación
de los archivos. `--workers 4` permite cuatro procesos de lectura independientes,
sin compartir un objeto NetCDF entre hilos; `--workers 1` hace la lectura secuencial.

Las distribuciones requieren `Ze` disponible y la variable correspondiente válida.
Se descartan valores negativos de `RR`, `LWC` y `WIDTH`; se conservan los ceros
cuando hay `Ze` disponible y los valores negativos válidos de `Ze` y `VEL`.
Los ceros de `RR/LWC` sin reflectividad disponible no se interpretan como medidas
útiles de ausencia de precipitación. Se respetan las máscaras NetCDF, sin aplicar
un umbral SNR adicional. Las marcas temporales se ajustan a una cadencia de 30 s
con tolerancia de 2 s y se conserva la primera muestra de cada intervalo repetido.
La cobertura se refiere al mes natural completo, en UTC.
En el piloto, RR, LWC y WIDTH usan una escala logarítmica con tramo lineal cerca
de cero (symlog), con transiciones en 0.01 mm/h, 0.001 g/m³ y 0.01 m/s. Ze y VEL
permanecen en escala lineal. Los cuartiles se calculan antes de cambiar la escala;
no se eliminan ceros ni extremos para mejorar la presentación.

Opciones: `--source` permite otra ubicación; `--instrument` admite `superficie`,
`meteo`, `disdrometer`, `radar` y `todos`. `--exclude VARIABLE=VALOR` es repetible y
permite excluir valores TOA5 solo tras confirmar su significado, por ejemplo
`--exclude 'radar_reflectivity=-9.999'`.

El radar exige fechas y limita la lectura a 48 archivos horarios por ejecución.
Puede ampliarse con `--max-radar-files`, teniendo en cuenta que los percentiles
exactos mantienen los perfiles seleccionados en memoria. No se leen los espectros.
La búsqueda presupone la organización `mrrpro82/AAAA/AAAAMM/AAAAMMDD/AAAAMMDD_HHMMSS.nc`
y archivos horarios, comprobada en la muestra de junio de 2026.

## Resultados

- `informe.html`: informe local que se abre en el navegador, sin servidor.
- `*_resumen.csv`: medidas válidas, ausentes, media, desviación estándar muestral,
  mínimo, percentiles 5 y 95, mediana y máximo.
- `*_mensual.csv`: estadísticos por mes natural para TOA5, con cobertura temporal
  y válida por variable respecto al mes completo.
- `*_codigos.csv`: frecuencias de estado, error y tiempo presente.
- `metadatos.json`: procedencia, periodo real, duplicados, huecos y decisiones.
- En meteo, `precipitacion_mensual.png`, `histograma_precipitacion_diaria.png`,
  `meteo_precipitacion_mensual.csv` y `meteo_precipitacion_diaria.csv`.
- En disdrómetro, `disdrometer_precipitacion_mensual.png`,
  `disdrometer_boxplot_intensidad.png`, `disdrometer_tipos_precipitacion.png`,
  `disdrometer_estudio_mensual.csv`, `disdrometer_tipos_mensuales.csv` y
  `disdrometer_precipitacion_diaria.csv`.

Use carpetas de salida diferentes para conservar informes anteriores.
Los archivos generados y los datos originales no se incluyen en Git.

## Tratamiento e interpretación

Las cabeceras TOA5 aportan los nombres y las unidades. Se excluyen `RECORD` y las
clases `N(...)`, `V(...)`, `spectrum(...)` del resumen básico. Se conservan ceros,
se descartan fechas inválidas y se conserva la primera fila para cada fecha
repetida. Los valores no numéricos e infinitos cuentan como ausentes. No hay
validación física ni filtro por los códigos de estado del sensor.

`-9.999` aparece en las muestras: se señala, pero se conserva salvo exclusión
explícita por variable. No se presupone que toda medida negativa sea inválida.
En **meteo**, por indicación del usuario, `7999` se convierte a NaN en todos los
canales numéricos. La precipitación se obtiene exclusivamente de `totalNTR`,
calculando diferencias no negativas entre lecturas válidas separadas exactamente
60 segundos. No se suma el contador directamente ni se atraviesan huecos o NaN.
Los descensos del contador se descartan como reinicios/correcciones; no se intenta
recuperar la precipitación durante esos intervalos. El minuto pertenece al día/mes
que termina en la lectura: la de las 00:00 cierra el último minuto del día anterior.
Se conservan las lecturas vecinas del filtro para calcular sus límites correctamente.
La zona horaria sigue siendo la original del archivo, sin resolver cambios de hora.

La gráfica mensual muestra cantidades observadas, con barras rayadas para los
meses incompletos y cruces para los que no tienen incrementos válidos. El total de
un mes completo solo se publica si tiene todos los minutos válidos. No se extrapola.
El histograma muestra **todos los días completos del periodo seleccionado**, incluidos
los secos; no incluye acumulados diarios parciales. La tabla contiene cobertura,
días completos, días completos con precipitación (>0 mm), media y máximo de los
días completos y máxima intensidad de un minuto derivada también de `totalNTR`.
Los CSV conservan cantidades observadas parciales y totales completos por separado.
El resto de los contadores se describe sin sumarlos. Los códigos no se promedian.

### Disdrómetro Parsivel2

Los acumulados mensuales usan diferencias válidas de `precipitation`, con las
mismas reglas de continuidad y cambio de día que meteo. `rain_intensity` se trata
como intensidad equivalente de precipitación (mm/h), sin restringirla a lluvia
líquida. `snow_intensity` es intensidad de espesor de nieve (equivalente volumétrico),
según el manual; no se suma a `rain_intensity`.

Se construye una caja por mes solo con intensidades positivas válidas. Cuartiles
con interpolación lineal y bigotes hasta los datos dentro de 1,5 veces el rango
intercuartílico. Los puntos exteriores se conservan. Cada etiqueta indica `n`
positivo y porcentaje sobre intensidades válidas, incluidos los ceros. Un mes
con ceros válidos pero sin positivos se distingue de otro sin datos. La tabla
incluye coberturas de acumulación e intensidad, mediana y P95 positivos y el
máximo de `rain_intensity` con su fecha. No se infiere independencia entre minutos.

Los tipos de precipitación se agrupan según **SYNOP wawa, tabla 4680**, del manual
local `Z:\HDP\meteo\BA_Parsivel2_EN_70210002BE.pdf`, apéndice D.1, página 49.
Se conservan los códigos desconocidos como «No clasificado». La gráfica apilada
excluye el código 0, que permanece en el CSV. Presenta horas equivalentes a 60
segundos por registro; no extrapola a huecos ni al mes completo.

Para los productos gráficos y su tabla se exige `sensor_status=0` y `error_code=0`
cuando existen estos canales. Sus valores ausentes o no nulos se excluyen. Los
resúmenes adicionales de los canales originales conservan los registros para
diagnóstico. No se construyen gráficas de reflectividad: el manual incluye
`−9.999` en su rango declarado (pp. 30 y 37), por lo que no se elimina
automáticamente ese valor de los resúmenes originales.

La búsqueda opcional de un evento se activa con `--rain-increment-column NOMBRE`
y `--instrument meteo` o `disdrometer`. Solo debe utilizarse después de confirmar
que ese canal contiene **incrementos en mm por minuto**. El programa comprueba
las unidades y rechaza los contadores conocidos, pero no puede confirmar la
semántica física del canal. Exige ventanas completas de minutos válidos, sin
rellenar huecos con ceros. Para esta búsqueda se invalidan negativos, infinitos,
ausentes y el valor sospechoso `7999`; esto no modifica los estadísticos mensuales.
`--event-threshold-mm` y `--event-hours` permiten ajustar el criterio. El resultado
se guarda en los metadatos y en el informe como candidato para revisión. No se
afirma que sea exclusivamente lluvia si el canal no distingue precipitación sólida.

La cobertura TOA5 supone 60 segundos entre registros y solo compara la primera y
última marca temporal observada. No equivale a cobertura de todo el periodo solicitado.
La zona horaria de TOA5 no está declarada; no se transforma ni se combina con radar.

El radar usa las unidades y máscaras declaradas en NetCDF. Resume cada distancia
por separado; no mezcla perfiles verticales. La distancia es la coordenada `range`,
no la altitud sobre el nivel del mar. Los promedios de dB/dBZ son aritméticos en
escala logarítmica, sin conversión a escala lineal. No se aplica umbral de SNR.
Se exige una malla y unidades constantes en los archivos del periodo.

En la exploración inicial los archivos TOA5 terminan el 4 de febrero de 2025;
el radar contiene carpetas de 2023 a 2026 y se ha comprobado una muestra de junio de
2026. El atributo `site_name` de esa muestra dice `AGORA-UGR`: se conserva en
metadatos para comprobar la identificación del emplazamiento.

## Verificación

```powershell
uv run --locked python -m unittest discover -s tests -v
```

Las pruebas usan archivos sintéticos para verificar valores ausentes, ceros,
duplicados, filtros temporales, códigos y máscaras/perfiles de NetCDF.
También comprueban meses sin datos y selección de una única ventana de evento,
sin aceptar huecos ni valores sospechosos como precipitación real.
Las del disdrómetro verifican cuartiles y bigotes, conservación de extremos,
denominadores de porcentajes, filtros de estado, códigos desconocidos y lectura
de contadores en los límites del periodo.
