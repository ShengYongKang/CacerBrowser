import type { ReactNode } from "react";

/**
 * Small inline country flags.
 *
 * Windows does not ship the regional-indicator glyphs that make 🇫🇷 render as a
 * flag, so emoji flags fall back to two tiny letters. Drawing them as SVG keeps
 * the manager self-contained (no CDN, works offline) and looks the same on every
 * machine.
 */

const W = 26;
const H = 18;

function star(cx: number, cy: number, outer: number, inner: number, fill: string, rotate = 0): ReactNode {
  const points: string[] = [];
  for (let index = 0; index < 10; index += 1) {
    const radius = index % 2 === 0 ? outer : inner;
    const angle = -Math.PI / 2 + rotate + (index * Math.PI) / 5;
    points.push(`${(cx + radius * Math.cos(angle)).toFixed(2)},${(cy + radius * Math.sin(angle)).toFixed(2)}`);
  }
  return <polygon points={points.join(" ")} fill={fill} />;
}

function art(country: string): ReactNode {
  switch (country) {
    case "US":
      return <>
        <rect width={W} height={H} fill="#ffffff" />
        {Array.from({ length: 7 }).map((_, index) => (
          <rect key={index} y={(index * 2 * H) / 13} width={W} height={H / 13} fill="#b22234" />
        ))}
        <rect width="10.4" height={(H * 7) / 13} fill="#3c3b6e" />
        {[[1.8, 1.8], [4.6, 1.8], [7.4, 1.8], [3.2, 4], [6, 4], [1.8, 6.2], [4.6, 6.2], [7.4, 6.2]].map(([cx, cy], index) => (
          <circle key={index} cx={cx} cy={cy} r="0.62" fill="#ffffff" />
        ))}
      </>;
    case "CA":
      return <>
        <rect width={W} height={H} fill="#ffffff" />
        <rect width="6.6" height={H} fill="#d52b1e" />
        <rect x="19.4" width="6.6" height={H} fill="#d52b1e" />
        <path d="M13 3.4l1.1 2.3 2.3-.6-.8 2.2 2.1 1.3-2.2 1.2.5 2.2-2.2-.8-.8 2.5-.8-2.5-2.2.8.5-2.2-2.2-1.2 2.1-1.3-.8-2.2 2.3.6z" fill="#d52b1e" />
      </>;
    case "GB":
      return <>
        <rect width={W} height={H} fill="#012169" />
        <path d="M0 0l26 18M26 0L0 18" stroke="#ffffff" strokeWidth="3.8" />
        <path d="M0 0l26 18M26 0L0 18" stroke="#c8102e" strokeWidth="1.9" />
        <path d="M13 0v18M0 9h26" stroke="#ffffff" strokeWidth="6" />
        <path d="M13 0v18M0 9h26" stroke="#c8102e" strokeWidth="3.4" />
      </>;
    case "FR":
      return <>
        <rect width={W} height={H} fill="#ffffff" />
        <rect width={W / 3} height={H} fill="#0055a4" />
        <rect x={(W * 2) / 3} width={W / 3} height={H} fill="#ef4135" />
      </>;
    case "DE":
      return <>
        <rect width={W} height={H / 3} fill="#000000" />
        <rect y={H / 3} width={W} height={H / 3} fill="#dd0000" />
        <rect y={(H * 2) / 3} width={W} height={H / 3} fill="#ffce00" />
      </>;
    case "ES":
      return <>
        <rect width={W} height={H} fill="#aa151b" />
        <rect y="4.5" width={W} height="9" fill="#f1bf00" />
        <rect x="5.2" y="6.6" width="2.2" height="4.2" rx="0.4" fill="#aa151b" />
      </>;
    case "IT":
      return <>
        <rect width={W} height={H} fill="#ffffff" />
        <rect width={W / 3} height={H} fill="#009246" />
        <rect x={(W * 2) / 3} width={W / 3} height={H} fill="#ce2b37" />
      </>;
    case "NL":
      return <>
        <rect width={W} height={H / 3} fill="#ae1c28" />
        <rect y={H / 3} width={W} height={H / 3} fill="#ffffff" />
        <rect y={(H * 2) / 3} width={W} height={H / 3} fill="#21468b" />
      </>;
    case "SE":
      return <>
        <rect width={W} height={H} fill="#006aa7" />
        <rect x="7.5" width="3.6" height={H} fill="#fecc00" />
        <rect y="7.2" width={W} height="3.6" fill="#fecc00" />
      </>;
    case "CH":
      return <>
        <rect width={W} height={H} fill="#d52b1e" />
        <rect x="11.5" y="4" width="3" height="10" fill="#ffffff" />
        <rect x="8" y="7.5" width="10" height="3" fill="#ffffff" />
      </>;
    case "AU":
      return <>
        <rect width={W} height={H} fill="#012169" />
        <g>
          <path d="M0 0l13 9M13 0L0 9" stroke="#ffffff" strokeWidth="2" />
          <path d="M0 0l13 9M13 0L0 9" stroke="#c8102e" strokeWidth="1" />
          <path d="M6.5 0v9M0 4.5h13" stroke="#ffffff" strokeWidth="3" />
          <path d="M6.5 0v9M0 4.5h13" stroke="#c8102e" strokeWidth="1.6" />
        </g>
        {star(19.5, 4, 1.5, 0.6, "#ffffff")}
        {star(22.4, 8, 1.5, 0.6, "#ffffff")}
        {star(19.5, 13.4, 1.5, 0.6, "#ffffff")}
        {star(23.6, 14.2, 1.1, 0.45, "#ffffff")}
        {star(6.4, 12.8, 1.1, 0.45, "#ffffff")}
      </>;
    case "JP":
      return <>
        <rect width={W} height={H} fill="#ffffff" />
        <circle cx={W / 2} cy={H / 2} r="4.8" fill="#bc002d" />
      </>;
    case "KR":
      return <>
        <rect width={W} height={H} fill="#ffffff" />
        <circle cx="13" cy="9" r="4" fill="#cd2e3a" />
        <path d="M9 9a4 4 0 008 0 4 4 0 01-8 0z" fill="#0047a0" />
        {[[3, 3.2], [23, 3.2], [3, 14.8], [23, 14.8]].map(([x, y], index) => (
          <g key={index} transform={`translate(${x} ${y})`} fill="#111111">
            <rect x="-2.2" y="-1.1" width="4.4" height="0.55" />
            <rect x="-2.2" y="-0.2" width="4.4" height="0.55" />
            <rect x="-2.2" y="0.7" width="4.4" height="0.55" />
          </g>
        ))}
      </>;
    case "SG":
      return <>
        <rect width={W} height={H} fill="#ffffff" />
        <rect width={W} height={H / 2} fill="#ed2939" />
        <circle cx="6" cy="4.6" r="3.1" fill="#ffffff" />
        <circle cx="7.5" cy="4.6" r="2.5" fill="#ed2939" />
        {[[10.6, 3.1], [13.4, 3.1], [11.4, 5.2], [12.8, 5.2], [12, 7]].map(([cx, cy], index) => (
          <circle key={index} cx={cx} cy={cy} r="0.55" fill="#ffffff" />
        ))}
      </>;
    case "IN":
      return <>
        <rect width={W} height={H / 3} fill="#ff9933" />
        <rect y={H / 3} width={W} height={H / 3} fill="#ffffff" />
        <rect y={(H * 2) / 3} width={W} height={H / 3} fill="#138808" />
        <circle cx={W / 2} cy={H / 2} r="2.5" fill="none" stroke="#000080" strokeWidth="0.7" />
        {Array.from({ length: 12 }).map((_, index) => {
          const angle = (index * Math.PI) / 6;
          return <line key={index} x1={13} y1={9} x2={13 + 2.2 * Math.cos(angle)} y2={9 + 2.2 * Math.sin(angle)} stroke="#000080" strokeWidth="0.3" />;
        })}
      </>;
    case "BR":
      return <>
        <rect width={W} height={H} fill="#009c3b" />
        <polygon points="13,2.2 24,9 13,15.8 2,9" fill="#ffdf00" />
        <circle cx="13" cy="9" r="3.7" fill="#002776" />
        <path d="M9.6 8.5c2.2 1.4 4.6 1.4 6.8 0" stroke="#ffffff" strokeWidth="1.4" fill="none" />
      </>;
    case "CN":
      return <>
        <rect width={W} height={H} fill="#de2910" />
        {star(5.6, 5.2, 2.7, 1.1, "#ffde00")}
        {[[10.4, 2.4, 0.9], [12.6, 4.2, 0.9], [12.6, 6.6, 0.9], [10.4, 8.4, 0.9]].map(([cx, cy, r], index) => (
          <g key={index}>{star(cx, cy, r, r * 0.42, "#ffde00")}</g>
        ))}
      </>;
    case "TW":
      return <>
        <rect width={W} height={H} fill="#fe0000" />
        <rect width="13" height="9" fill="#000095" />
        <circle cx="6.5" cy="4.5" r="2.3" fill="#ffffff" />
        {Array.from({ length: 12 }).map((_, index) => {
          const angle = (index * Math.PI) / 6;
          return <line key={index} x1={6.5 + 2.5 * Math.cos(angle)} y1={4.5 + 2.5 * Math.sin(angle)} x2={6.5 + 3.7 * Math.cos(angle)} y2={4.5 + 3.7 * Math.sin(angle)} stroke="#ffffff" strokeWidth="0.7" />;
        })}
      </>;
    case "HK":
      return <>
        <rect width={W} height={H} fill="#de2910" />
        {Array.from({ length: 5 }).map((_, index) => {
          const angle = -Math.PI / 2 + (index * 2 * Math.PI) / 5;
          return <circle key={index} cx={13 + 2.4 * Math.cos(angle)} cy={9 + 2.4 * Math.sin(angle)} r="1.7" fill="#ffffff" />;
        })}
        <circle cx="13" cy="9" r="1.15" fill="#de2910" />
      </>;
    default:
      return <>
        <rect width={W} height={H} fill="#eef1f6" />
        <circle cx={W / 2} cy={H / 2} r="6" fill="none" stroke="#98a2b3" strokeWidth="1.1" />
        <path d="M7 9h12M13 3c2.2 2 2.2 10 0 12M13 3c-2.2 2-2.2 10 0 12" fill="none" stroke="#98a2b3" strokeWidth="1.1" />
      </>;
  }
}

export default function Flag({ country, size = 24, className }: { country: string; size?: number; className?: string }) {
  const label = country || "自动地区";
  return <svg
    className={`flag-icon${className ? ` ${className}` : ""}`}
    width={size}
    height={(size * H) / W}
    viewBox={`0 0 ${W} ${H}`}
    role="img"
    aria-label={label}
  >
    {art(country)}
  </svg>;
}
