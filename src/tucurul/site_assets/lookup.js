// Búsqueda pura de una sección dentro del JSON compacto por entidad.
// Formato: {entidad, columns: [...], municipios: {clave: nombre}, rows: [[...]]}

export function findSeccion(data, seccion) {
  const n = Number(seccion);
  if (!Number.isFinite(n) || !data || !Array.isArray(data.rows)) return null;
  const iSeccion = data.columns.indexOf("seccion");
  const iDF = data.columns.indexOf("distrito_federal");
  const iDL = data.columns.indexOf("distrito_local");
  const iMun = data.columns.indexOf("municipio");
  for (const row of data.rows) {
    if (row[iSeccion] === n) {
      const municipio = row[iMun];
      return {
        seccion: n,
        distrito_federal: row[iDF],
        distrito_local: row[iDL],
        municipio,
        municipio_nombre: data.municipios[String(municipio)] ?? "",
      };
    }
  }
  return null;
}
