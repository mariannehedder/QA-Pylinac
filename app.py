from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import pydicom
import streamlit as st
from pylinac import PicketFence, WinstonLutz, WinstonLutzMultiTargetMultiField
from pylinac.core.scale import MachineScale
from pylinac.picketfence import MLC, Orientation
from pylinac.winston_lutz import BBArrangement


st.set_page_config(page_title="QA Pylinac", page_icon=":microscope:", layout="wide")


def save_uploaded_file(uploaded_file, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    file_path = destination / Path(uploaded_file.name).name
    with file_path.open("wb") as buffer:
        buffer.write(uploaded_file.getbuffer())
    return file_path


def save_uploaded_files(uploaded_files, destination: Path) -> list[Path]:
    return [save_uploaded_file(file, destination) for file in uploaded_files]


def extract_zip(zip_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not str(target).startswith(str(destination.resolve())):
                raise ValueError(f"Arquivo ZIP contem caminho inseguro: {member.filename}")
        archive.extractall(destination)
    return destination


def uploaded_dicom_files(uploaded_files, work_dir: Path, input_name: str) -> list[Path]:
    input_dir = work_dir / input_name
    saved_files = save_uploaded_files(uploaded_files, input_dir)
    zip_files = [path for path in saved_files if path.suffix.lower() == ".zip"]
    if len(zip_files) == 1 and len(saved_files) == 1:
        input_dir = extract_zip(zip_files[0], work_dir / f"{input_name}_zip")

    dicom_files = [
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".dcm", ".dicom", ""}
    ]
    return sorted(dicom_files)


def dicom_text_values(path: Path) -> list[str]:
    dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    values = [path.name, path.stem]
    for element in dataset.iterall():
        if element.VR in {"LO", "SH", "ST", "LT", "UT", "CS"}:
            value = element.value
            if isinstance(value, (list, tuple)):
                values.extend(str(item) for item in value)
            else:
                values.append(str(value))
    return values


def identify_field_name(path: Path, expected_names: set[str]) -> str | None:
    for value in dicom_text_values(path):
        normalized = value.strip().upper()
        if normalized in expected_names:
            return normalized
    return None


def axis_mapping_by_filename(axis_table: pd.DataFrame, dicom_files: list[Path]) -> dict[str, tuple[int, int, int]]:
    expected_axes = {
        str(row["campo"]).strip().upper(): (
            int(float(row["gantry"])),
            int(float(row["collimator"])),
            int(float(row["couch"])),
        )
        for _, row in axis_table.dropna().iterrows()
        if str(row.get("campo", "")).strip()
    }
    mapping = {}
    missing = []
    for path in dicom_files:
        field_name = identify_field_name(path, set(expected_axes))
        if field_name is None:
            missing.append(path.name)
            continue
        mapping[path.name] = expected_axes[field_name]
    if missing:
        missing_text = "\n".join(missing)
        raise ValueError(
            "Nao foi possivel identificar o campo de alguns DICOMs. "
            "Verifique se os metadados contem nomes como A1/A2 ou M1/M2.\n\n"
            f"Arquivos sem campo identificado:\n{missing_text}"
        )
    return mapping


def read_bytes(path: Path) -> bytes:
    with path.open("rb") as file:
        return file.read()


def results_text(analysis) -> str:
    result = analysis.results()
    if isinstance(result, str):
        return result
    return "\n".join(str(line) for line in result)


def download_pdf(pdf_path: Path, label: str) -> None:
    st.download_button(
        label=label,
        data=read_bytes(pdf_path),
        file_name=pdf_path.name,
        mime="application/pdf",
        use_container_width=True,
    )


def common_inputs(key_prefix: str) -> dict:
    with st.expander("Configuracoes avancadas", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            bb_proximity = st.number_input(
                "Proximidade BB (mm)",
                min_value=0.1,
                value=20.0 if key_prefix == "cube" else 10.0,
                step=0.5,
                key=f"{key_prefix}_bb_proximity",
                help="Distancia maxima esperada entre a BB detectada e a posicao nominal. Normalmente nao precisa alterar.",
            )
        with col2:
            use_filenames = st.checkbox(
                "Usar angulos dos nomes dos arquivos",
                value=False,
                key=f"{key_prefix}_use_filenames",
                help="Ative somente se os DICOMs nao tiverem os angulos corretamente nos metadados e voce nomeou os arquivos com os angulos.",
            )
            open_field = st.checkbox(
                "Campo aberto",
                value=False,
                key=f"{key_prefix}_open_field",
                help="Ative apenas se as imagens forem de campo aberto, sem borda de campo bem definida.",
            )
            low_density = st.checkbox(
                "BB de baixa densidade",
                value=False,
                key=f"{key_prefix}_low_density",
                help="Ative apenas se a BB aparecer escura/hipodensa em vez de brilhante/alta densidade.",
            )

    return {
        "sid": None,
        "bb_proximity": bb_proximity,
        "machine_scale": MachineScale.IEC61217,
        "use_filenames": use_filenames,
        "open_field": open_field,
        "low_density": low_density,
    }


def wl_cube_page() -> None:
    st.subheader("WL Cube")
    st.write("Use esta opcao para o Winston-Lutz convencional com um unico alvo/BB.")

    uploaded_files = st.file_uploader(
        "Envie os DICOMs do Winston-Lutz ou um ZIP com as imagens",
        type=["dcm", "dicom", "zip"],
        accept_multiple_files=True,
        key="cube_upload",
    )

    params = common_inputs("cube")

    st.caption("Mapa dos campos do WL Cube. Os nomes devem bater com os nomes dos campos nas imagens/DICOMs.")
    default_axis_mapping = pd.DataFrame(
        {
            "campo": ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12", "A13"],
            "gantry": [0, 0, 0, 0, 0, 0, 0, 90, 90, 180, 180, 270, 270],
            "collimator": [0, 90, 270, 45, 225, 135, 315, 90, 270, 0, 90, 90, 270],
            "couch": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        }
    )
    use_axis_mapping = st.checkbox(
        "Usar tabela de campos A1-A13",
        value=True,
        help="Use esta opcao quando os campos se chamam A1, A2, ... e os angulos precisam ser informados pela tabela.",
    )
    axis_table = st.data_editor(
        default_axis_mapping,
        num_rows="dynamic",
        use_container_width=True,
        disabled=not use_axis_mapping,
        key="cube_axis_mapping",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        bb_size = st.number_input("Tamanho da BB (mm)", min_value=0.1, value=5.0, step=0.5)
        snap_tolerance = st.number_input("Snap tolerance (mm)", min_value=0.0, value=3.0, step=0.5)
    with col2:
        gantry_reference = st.number_input("Referencia gantry", value=0.0, step=1.0)
        collimator_reference = st.number_input("Referencia colimador", value=0.0, step=1.0)
    with col3:
        couch_reference = st.number_input("Referencia mesa", value=0.0, step=1.0)
        apply_virtual_shift = st.checkbox("Aplicar deslocamento virtual", value=False)

    if st.button("Analisar WL Cube", type="primary", disabled=not uploaded_files):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            pdf_path = work_dir / "winston_lutz_wl_cube.pdf"
            summary_path = work_dir / "winston_lutz_wl_cube.png"

            try:
                dicom_files = uploaded_dicom_files(uploaded_files, work_dir, "wl_cube_input")
                if not dicom_files:
                    st.error("Nenhum arquivo DICOM foi encontrado no upload.")
                    return
                axis_mapping = None
                if use_axis_mapping:
                    axis_mapping = axis_mapping_by_filename(axis_table, dicom_files)
                    if not axis_mapping:
                        st.error("Informe pelo menos um campo na tabela A1-A13.")
                        return

                with st.spinner("Analisando WL Cube..."):
                    wl = WinstonLutz(
                        str(dicom_files[0].parent),
                        use_filenames=params["use_filenames"],
                        axis_mapping=axis_mapping,
                        sid=params["sid"],
                    )
                    wl.analyze(
                        bb_size_mm=bb_size,
                        machine_scale=params["machine_scale"],
                        low_density_bb=params["low_density"],
                        open_field=params["open_field"],
                        apply_virtual_shift=apply_virtual_shift,
                        snap_tolerance=snap_tolerance,
                        gantry_reference=gantry_reference,
                        collimator_reference=collimator_reference,
                        couch_reference=couch_reference,
                        bb_proximity_mm=params["bb_proximity"],
                    )
                    wl.save_summary(str(summary_path))
                    wl.publish_pdf(str(pdf_path))
            except Exception as exc:
                st.error("Nao foi possivel concluir a analise do WL Cube.")
                st.exception(exc)
                return

            st.success("Analise concluida.")
            if summary_path.exists():
                st.image(str(summary_path), caption="Resumo WL Cube", use_container_width=True)
            st.code(results_text(wl), language="text")
            download_pdf(pdf_path, "Baixar PDF WL Cube")


def multimet_page() -> None:
    st.subheader("MultiMet")
    st.write("Use esta opcao para Winston-Lutz MultiTarget/MultiField, com multiplos alvos/campos.")

    uploaded_files = st.file_uploader(
        "Envie os DICOMs do MultiMet ou um ZIP com as imagens",
        type=["dcm", "dicom", "zip"],
        accept_multiple_files=True,
        key="multimet_upload",
    )

    params = common_inputs("multimet")

    st.caption("Mapa dos campos do MultiMet. Os nomes devem bater com os nomes dos campos nas imagens/DICOMs.")
    default_axis_mapping = pd.DataFrame(
        {
            "campo": ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"],
            "gantry": [180, 90, 90, 270, 270, 0, 0, 0, 0, 0],
            "collimator": [90, 90, 90, 90, 90, 90, 0, 0, 270, 0],
            "couch": [0, 0, 0, 0, 0, 0, 90, 270, 0, 0],
        }
    )
    use_axis_mapping = st.checkbox(
        "Usar tabela de campos M1-M10",
        value=True,
        help="Use esta opcao quando os campos se chamam M1, M2, ... e os angulos precisam ser informados pela tabela.",
    )
    axis_table = st.data_editor(
        default_axis_mapping,
        num_rows="dynamic",
        use_container_width=True,
        disabled=not use_axis_mapping,
        key="multimet_axis_mapping",
    )

    st.info("O MultiMet usa o arranjo padrao da biblioteca do pylinac: BBArrangement.SNC_MULTIMET.")

    if st.button("Analisar MultiMet", type="primary", disabled=not uploaded_files):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            pdf_path = work_dir / "winston_lutz_multimet.pdf"
            summary_path = work_dir / "winston_lutz_multimet.png"

            try:
                dicom_files = uploaded_dicom_files(uploaded_files, work_dir, "multimet_input")
                if not dicom_files:
                    st.error("Nenhum arquivo DICOM foi encontrado no upload.")
                    return
                axis_mapping = None
                if use_axis_mapping:
                    axis_mapping = axis_mapping_by_filename(axis_table, dicom_files)
                    if not axis_mapping:
                        st.error("Informe pelo menos um campo na tabela M1-M10.")
                        return

                with st.spinner("Analisando MultiMet..."):
                    wl = WinstonLutzMultiTargetMultiField(
                        str(dicom_files[0].parent),
                        use_filenames=params["use_filenames"],
                        axis_mapping=axis_mapping,
                        sid=params["sid"],
                    )
                    wl.analyze(
                        bb_arrangement=BBArrangement.SNC_MULTIMET,
                        is_open_field=params["open_field"],
                        is_low_density=params["low_density"],
                        machine_scale=params["machine_scale"],
                        bb_proximity_mm=params["bb_proximity"],
                    )
                    wl.save_summary(str(summary_path))
                    wl.publish_pdf(str(pdf_path))
            except Exception as exc:
                st.error("Nao foi possivel concluir a analise do MultiMet.")
                st.exception(exc)
                return

            st.success("Analise concluida.")
            if summary_path.exists():
                st.image(str(summary_path), caption="Resumo MultiMet", use_container_width=True)
            st.code(results_text(wl), language="text")
            download_pdf(pdf_path, "Baixar PDF MultiMet")


def picket_fence_page() -> None:
    st.subheader("Picket Fence")
    st.write("Use esta opcao para analisar o posicionamento das laminas do MLC no teste Picket Fence.")

    uploaded_files = st.file_uploader(
        "Envie a imagem DICOM do Picket Fence",
        type=["dcm", "dicom"],
        accept_multiple_files=True,
        key="picket_fence_upload",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        tolerance = st.number_input(
            "Tolerancia (mm)",
            min_value=0.0,
            value=0.5,
            step=0.1,
            help="Erro maximo permitido para o posicionamento das laminas. Valores acima desta tolerancia falham.",
        )
    with col2:
        action_tolerance = st.number_input(
            "Nivel de acao (mm, opcional)",
            min_value=0.0,
            value=0.0,
            step=0.1,
            help="Use 0 para nao aplicar nivel de acao separado. A tolerancia principal continua valendo.",
        )
    with col3:
        mlc_name = st.selectbox(
            "MLC",
            [mlc.name for mlc in MLC],
            index=[mlc.name for mlc in MLC].index("MILLENNIUM"),
            help="Modelo do MLC usado na aquisicao. Escolha o modelo correspondente ao equipamento.",
        )

    with st.expander("Configuracoes avancadas", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            num_pickets = st.number_input(
                "Numero de faixas",
                min_value=0,
                value=0,
                step=1,
                help="Quantidade de faixas irradiadas no teste. Use 0 para deteccao automatica.",
            )
            nominal_gap = st.number_input(
                "Abertura nominal (mm)",
                min_value=0.1,
                value=3.0,
                step=0.1,
                help="Abertura esperada entre as laminas durante o teste. Altere apenas se o plano usar outra abertura.",
            )
            crop_mm = st.number_input(
                "Corte das bordas (mm)",
                min_value=0,
                value=3,
                step=1,
                help="Remove alguns milimetros das bordas da imagem para evitar artefatos na analise.",
            )
        with col2:
            orientation_label = st.selectbox(
                "Orientacao",
                ["Automatica", "UP_DOWN", "LEFT_RIGHT"],
                index=0,
                help="Direcao das faixas na imagem. Deixe em Automatica, salvo se a deteccao errar.",
            )
            invert = st.checkbox(
                "Inverter imagem",
                value=False,
                help="Inverte claro/escuro. Use se o pylinac nao detectar as faixas por causa do contraste.",
            )
            separate_leaves = st.checkbox(
                "Analisar folhas separadamente",
                value=False,
                help="Analisa cada folha de forma individualizada. Normalmente fica desligado para CQ rotineiro.",
            )
        with col3:
            sag_adjustment = st.number_input(
                "Ajuste de sag (mm)",
                value=0.0,
                step=0.1,
                help="Correcao para queda mecanica/gravitacional conhecida. Use 0 se nao houver correcao definida.",
            )
            height_threshold = st.number_input(
                "Height threshold",
                min_value=0.0,
                max_value=1.0,
                value=0.5,
                step=0.05,
                help="Limiar usado para detectar os picos/faixas. Altere apenas se a deteccao automatica estiver ruim.",
            )
            edge_threshold = st.number_input(
                "Edge threshold",
                min_value=0.0,
                value=1.5,
                step=0.1,
                help="Limiar usado para detectar as bordas das faixas. Altere apenas se as bordas forem detectadas errado.",
            )

    if st.button("Analisar Picket Fence", type="primary", disabled=not uploaded_files):
        with tempfile.TemporaryDirectory() as temp_dir:
            work_dir = Path(temp_dir)
            input_dir = work_dir / "picket_fence_input"
            saved_files = save_uploaded_files(uploaded_files, input_dir)
            pdf_path = work_dir / "picket_fence.pdf"
            image_path = work_dir / "picket_fence.png"

            try:
                with st.spinner("Analisando Picket Fence..."):
                    if len(saved_files) == 1:
                        pf = PicketFence(str(saved_files[0]), mlc=MLC[mlc_name], crop_mm=int(crop_mm))
                    else:
                        pf = PicketFence.from_multiple_images(
                            [str(path) for path in saved_files],
                            mlc=MLC[mlc_name],
                            crop_mm=int(crop_mm),
                        )

                    orientation = None if orientation_label == "Automatica" else Orientation[orientation_label]
                    pf.analyze(
                        tolerance=tolerance,
                        action_tolerance=action_tolerance if action_tolerance > 0 else None,
                        num_pickets=int(num_pickets) if num_pickets > 0 else None,
                        sag_adjustment=sag_adjustment,
                        orientation=orientation,
                        invert=invert,
                        height_threshold=height_threshold,
                        edge_threshold=edge_threshold,
                        separate_leaves=separate_leaves,
                        nominal_gap_mm=nominal_gap,
                    )
                    pf.save_analyzed_image(str(image_path))
                    pf.publish_pdf(str(pdf_path))
            except Exception as exc:
                st.error("Nao foi possivel concluir a analise do Picket Fence.")
                st.exception(exc)
                return

            st.success("Analise concluida.")
            if image_path.exists():
                st.image(str(image_path), caption="Picket Fence analisado", use_container_width=True)
            st.code(results_text(pf), language="text")
            download_pdf(pdf_path, "Baixar PDF Picket Fence")


def main() -> None:
    st.title("QA Pylinac")
    st.write("Selecione a aba da analise desejada e envie as imagens correspondentes.")

    wl_tab, picket_tab = st.tabs(["Winston-Lutz", "Picket Fence"])

    with wl_tab:
        phantom = st.radio(
            "Phantom",
            ["WL Cube", "MultiMet"],
            horizontal=True,
            help="WL Cube usa WinstonLutz convencional. MultiMet usa WinstonLutzMultiTargetMultiField.",
        )
        if phantom == "WL Cube":
            wl_cube_page()
        else:
            multimet_page()

    with picket_tab:
        picket_fence_page()


if __name__ == "__main__":
    main()
