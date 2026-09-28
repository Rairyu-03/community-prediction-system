import mark from "./assets/community-mark.svg";

/** Shared asset is bundled into both standalone and embedded builds. */
export function BrandMark() {
  return <img className="brand-mark" src={mark} alt="社区建筑标识" width={38} height={38} />;
}
