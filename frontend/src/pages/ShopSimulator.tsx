import { useParams } from 'react-router-dom'
import PagePlaceholder from '../components/PagePlaceholder'

export default function ShopSimulator() {
  const { id } = useParams()
  return <PagePlaceholder title="Shopkeeper phone simulator" detail={`Merchant: ${id}`} />
}
