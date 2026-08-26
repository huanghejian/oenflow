import type { AssetItem, AssetRecord } from "./autoflowTypes";

type AssetColumnProps = {
  title: string;
  caption: string;
  assets: AssetItem[];
  registry: Record<string, AssetRecord>;
  apiBase: string;
  busyKey: string;
  onUpload: (assetId: string, file: File) => void;
};

function sourceLabel(record?: AssetRecord): string {
  if (!record) return "待上传";
  if (record.source === "user_upload") return "用户图片";
  if (record.source === "bundled_demo_asset") return "内置图片";
  if (record.source === "derived_reference_image") return "生成图";
  return "已绑定";
}

function assetPrompt(asset: AssetItem): string {
  return asset.asset_prompt || asset.localized_prompt || asset.prompt || asset.description || "暂无生资产提示词";
}

export default function AssetColumn({ title, caption, assets, registry, apiBase, busyKey, onUpload }: AssetColumnProps) {
  return (
    <section className="assetColumn">
      <header>
        <div>
          <h3>{title}</h3>
          <p>{caption}</p>
        </div>
        <b>{assets.length}</b>
      </header>
      <div className="assetColumnList">
        {assets.map((asset) => {
          const record = registry[asset.id];
          const uploading = busyKey === `upload:${asset.id}`;
          return (
            <article className={record ? "autoAssetCard bound" : "autoAssetCard"} key={asset.id}>
              <div className="assetPreview">
                {record?.url ? <img src={`${apiBase}${record.url}`} alt={asset.name} /> : <span aria-label="未上传图片">+</span>}
              </div>
              <div className="assetCopy">
                <strong>{asset.name}</strong>
                <p>{assetPrompt(asset)}</p>
                {asset.image_prompts && Object.keys(asset.image_prompts).length > 0 ? (
                  <details>
                    <summary>3套模型提示词</summary>
                    {Object.entries(asset.image_prompts).map(([model, prompt]) => (
                      <small key={model}><b>{model}</b>：{prompt}</small>
                    ))}
                  </details>
                ) : null}
              </div>
              <footer>
                <span>{sourceLabel(record)}</span>
                <label>
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    disabled={Boolean(busyKey)}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) onUpload(asset.id, file);
                      event.currentTarget.value = "";
                    }}
                  />
                  <i>{uploading ? "上传中" : record ? "替换" : "上传"}</i>
                </label>
              </footer>
            </article>
          );
        })}
      </div>
    </section>
  );
}
