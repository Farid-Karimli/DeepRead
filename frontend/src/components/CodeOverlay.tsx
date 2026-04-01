import {
  BoundingBox,
  type BoundingBoxProps,
  type BoundingBoxType,
  computeBoundingBoxStyle,
  DocumentContext,
  HighlightOverlay,
  TransformContext,
} from '@allenai/pdf-components';

import * as React from 'react';
import { createPortal } from 'react-dom';
import { useSidePanel } from '../context/SidePanelContext.tsx';

/** Geometry matches `BoundingBox`; `tooltip` is shown on hover (native + optional floating). */
export type BoundingBoxWithTooltip = BoundingBoxType & {
  file_info: string;
  code: string;
  hitKey: string;
};

type overlayProps = {
  pageIndex: number;
  boxes: Array<BoundingBoxWithTooltip>;
};

/**
 * Invisible hit target on top of the page overlay. `HighlightOverlay` only uses BoundingBox
 * props for SVG mask geometry — it does not mount DOM nodes, so there is nothing to hover
 * unless we add a separate layer like this.
 */
function PdfBoundingHitTarget({
  box,
  pageIndex,
}: {
  box: BoundingBoxWithTooltip;
  pageIndex: number;
}) {
  const { pageDimensions } = React.useContext(DocumentContext);
  const { rotation, scale } = React.useContext(TransformContext);
  const [floating, setFloating] = React.useState<{ x: number; y: number } | null>(null);
  const [hover, setHover] = React.useState(false);
  const leaveTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const { showCode } = useSidePanel();

  if (box.page !== pageIndex) {
    return null;
  }

  const { top, left, width, height } = computeBoundingBoxStyle(
    { top: box.top, left: box.left, width: box.width, height: box.height },
    pageDimensions,
    rotation,
    scale,
  );

  const style: React.CSSProperties = {
    position: 'absolute',
    top,
    left,
    width,
    height,
    zIndex: 2,
    boxSizing: 'content-box',
    opacity: hover ? 0.5 : 0.25,
    outline: hover ? '2px solid rgba(0, 180, 255, 0.85)' : 'none',
    backgroundColor: hover ? 'rgba(0, 160, 255, 0.25)' : 'orange',
    cursor: 'help',
    pointerEvents: 'auto',
    transition: 'opacity 80ms ease',
  };

  const tooltipNode =
    floating &&
    createPortal(
      <div
        className="pdf-hit-tooltip"
        style={{
          position: 'fixed',
          left: floating.x,
          top: floating.y,
          zIndex: 10000,
          maxWidth: 520,
          padding: '8px 10px',
          fontSize: 12,
          lineHeight: 1.35,
          background: 'rgba(20, 20, 24, 0.95)',
          color: '#f4f4f5',
          borderRadius: 6,
          boxShadow: '0 4px 24px rgba(0,0,0,0.35)',
          pointerEvents: 'auto',
          whiteSpace: 'pre-wrap',
        }}
        onMouseEnter={() => {
          if (leaveTimer.current) clearTimeout(leaveTimer.current);
        }}
        onMouseLeave={() => {
          setHover(false);
          setFloating(null);
        }}
      >
        {box.file_info}
        <button onClick={() => showCode(box.code)}>View Code</button>
      </div>,
      document.body,
    );

  return (
    <>
      <div
        style={style}
        title={box.code}
        role="button"
        tabIndex={0}
        onMouseEnter={(e) => {
          if (leaveTimer.current) clearTimeout(leaveTimer.current);
          setHover(true);
          setFloating(prev => prev ?? { x: e.clientX + 12, y: e.clientY + 12 });
        }}
        onMouseLeave={() => {
          leaveTimer.current = setTimeout(() => {
            setHover(false);
            setFloating(null);
          }, 150);
        }}
      />
      {tooltipNode}
    </>
  );
}

function maskBoundingBoxes(
  pageIndex: number,
  boxes: Array<BoundingBoxWithTooltip>,
): Array<React.ReactElement<BoundingBoxProps>> {
  const out: Array<React.ReactElement<BoundingBoxProps>> = [];
  boxes.forEach((box) => {
    if (box.page !== pageIndex) return;
    out.push(
      <BoundingBox
        key={`mask-${box.hitKey}`}
        page={box.page}
        top={box.top}
        left={box.left}
        width={box.width}
        height={box.height}
        className="reader__sample-highlight-overlay__bbox"
      />,
    );
  });
  return out;
}

/**
 * Mask cutouts (HighlightOverlay) + separate invisible hit targets for hover tooltips.
 */
export const HighlightOverlayDemo: React.FunctionComponent<overlayProps> = ({
  pageIndex,
  boxes,
}) => {
  return (
    <>
      <HighlightOverlay pageIndex={pageIndex}>
        {maskBoundingBoxes(pageIndex, boxes)}
      </HighlightOverlay>
      {boxes.map((box) => (
        <PdfBoundingHitTarget key={`hit-${box.hitKey}`} box={box} pageIndex={pageIndex} />
      ))}
    </>
  );
};
