import { findSeccion } from "./lookup.js";

const form = document.getElementById("form-seccion");
const selectEntidad = document.getElementById("entidad");
const inputSeccion = document.getElementById("seccion");
const resultado = document.getElementById("resultado");

const catalogos = new Map(); // clave -> JSON por entidad
const nombres = new Map(); // clave -> nombre de la entidad

async function cargarEntidades() {
  const resp = await fetch("data/states.json");
  const estados = await resp.json();
  selectEntidad.innerHTML =
    '<option value="" disabled selected>Elige una entidad</option>';
  for (const e of estados) {
    const opt = document.createElement("option");
    opt.value = e.clave;
    opt.textContent = `${e.clave} — ${e.nombre}`;
    selectEntidad.appendChild(opt);
    nombres.set(e.clave, e.nombre);
  }
}

async function cargarCatalogo(clave) {
  if (!catalogos.has(clave)) {
    const resp = await fetch(`data/secciones/${clave}.json`);
    if (!resp.ok) throw new Error(`Sin datos para ${clave}`);
    catalogos.set(clave, await resp.json());
  }
  return catalogos.get(clave);
}

function mostrarResultado(key, nombreEntidad) {
  if (key === null) {
    resultado.innerHTML = "";
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = `La sección ${inputSeccion.value} no existe en ${nombreEntidad}.`;
    resultado.appendChild(p);
    return;
  }
  const dl = document.createElement("dl");
  const items = [
    ["Distrito federal", key.distrito_federal],
    ["Distrito local", key.distrito_local],
    ["Municipio", `${key.municipio} — ${key.municipio_nombre}`],
  ];
  for (const [dt, dd] of items) {
    const elDt = document.createElement("dt");
    elDt.textContent = dt;
    const elDd = document.createElement("dd");
    elDd.textContent = dd;
    dl.append(elDt, elDd);
  }
  resultado.innerHTML = "";
  resultado.appendChild(dl);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const clave = selectEntidad.value;
  if (!clave) return;
  try {
    const data = await cargarCatalogo(clave);
    mostrarResultado(
      findSeccion(data, inputSeccion.value),
      nombres.get(clave) ?? clave,
    );
  } catch {
    resultado.textContent =
      "No se pudieron cargar los datos de la entidad; intenta de nuevo.";
  }
});

cargarEntidades().catch(() => {
  selectEntidad.innerHTML =
    '<option value="" disabled selected>Error al cargar entidades</option>';
});
